"""Convert only neural compute blocks; preserve preprocessing and box math precision."""
import collections
import copy
import hashlib
from pathlib import Path

import numpy as np
import onnx
from onnx import TensorProto, helper, numpy_helper

PREFIXES = ('/detector/backbone/', '/detector/rpn/head/',
            '/detector/roi_heads/box_head/', '/detector/roi_heads/box_predictor/')
OPS = {'Conv', 'Relu', 'Add', 'MaxPool', 'Resize', 'Gemm', 'Flatten'}


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def subgraph_inputs(node):
    names = set(node.input)
    for attr in node.attribute:
        graphs = [attr.g] if attr.type == onnx.AttributeProto.GRAPH else list(attr.graphs)
        for graph in graphs:
            names.update(output.name for output in graph.output)
            for child in graph.node:
                names.update(subgraph_inputs(child))
    return names


def convert(source, destination, check=lambda: None):
    source, destination = Path(source), Path(destination)
    if source.resolve() == destination.resolve():
        raise ValueError('Source and destination must differ.')
    check()
    digest = sha(source)
    model = onnx.shape_inference.infer_shapes(onnx.load(source))
    graph = model.graph
    infos = {v.name: v for v in list(graph.input) + list(graph.output) + list(graph.value_info)}
    types = {name: v.type.tensor_type.elem_type for name, v in infos.items()}
    initializers = {v.name: v for v in graph.initializer}
    types.update({name: v.data_type for name, v in initializers.items()})
    selected = {n.name for n in graph.node if n.name.startswith(PREFIXES) and n.op_type in OPS}
    if not selected:
        raise ValueError('No supported neural blocks found for FP16 conversion.')
    half_outputs = {name for n in graph.node if n.name in selected for name in n.output if types.get(name) == TensorProto.FLOAT}
    needed_full = {v.name for v in graph.output}
    for node in graph.node:
        if node.name not in selected:
            needed_full.update(subgraph_inputs(node))
        elif node.op_type == 'Resize':
            # Resize coordinates/scales retain their declared original types.
            needed_full.update(node.input[1:])
    half_names = {name: name + '__mixed_fp16' for name in half_outputs}
    cast_cache, half_initializers, output_nodes = {}, {}, []

    def half_input(name):
        if name in half_names:
            return half_names[name]
        if name in initializers:
            if name not in half_initializers:
                data = numpy_helper.to_array(initializers[name])
                half = data.astype(np.float16)
                if not np.isfinite(half).all():
                    raise ValueError('Weights exceed the finite FP16 range. Use FP32.')
                half_initializers[name] = numpy_helper.from_array(half, name + '__mixed_fp16')
            return half_initializers[name].name
        if name not in cast_cache:
            cast_cache[name] = name + '__to_fp16'
            output_nodes.append(helper.make_node('Cast', [name], [cast_cache[name]],
                                                name=name + '__cast_fp16', to=TensorProto.FLOAT16))
        return cast_cache[name]

    for original in graph.node:
        check()
        node = copy.deepcopy(original)
        if node.name in selected:
            for i, name in enumerate(node.input):
                if node.op_type == 'Resize' and i > 0:
                    continue
                if types.get(name) == TensorProto.FLOAT:
                    node.input[i] = half_input(name)
            for i, name in enumerate(node.output):
                if name in half_names:
                    node.output[i] = half_names[name]
        output_nodes.append(node)
        if original.name in selected:
            for name in original.output:
                if name in half_names and name in needed_full:
                    output_nodes.append(helper.make_node('Cast', [half_names[name]], [name],
                                                        name=name + '__cast_fp32', to=TensorProto.FLOAT))
    del graph.node[:]
    graph.node.extend(output_nodes)
    used = set()
    for node in graph.node:
        used.update(subgraph_inputs(node))
    preserved = [v for v in graph.initializer if v.name in used]
    del graph.initializer[:]
    graph.initializer.extend(preserved + list(half_initializers.values()))
    for name, renamed in half_names.items():
        value = copy.deepcopy(infos[name])
        value.name = renamed
        value.type.tensor_type.elem_type = TensorProto.FLOAT16
        graph.value_info.append(value)
    # Remove stale value info for original tensors no longer emitted by any node.
    defined = {v.name for v in graph.input} | {v.name for v in graph.initializer} | {s for n in graph.node for s in n.output}
    kept = [v for v in graph.value_info if v.name in defined]
    del graph.value_info[:]
    graph.value_info.extend(kept)
    model = onnx.shape_inference.infer_shapes(model, strict_mode=True)
    onnx.checker.check_model(model, full_check=True)
    destination.parent.mkdir(parents=True, exist_ok=True)
    check()
    onnx.save(model, destination)
    if sha(source) != digest:
        raise ValueError('Source changed during conversion.')
    metadata = dict(source_sha256=digest, model_sha256=sha(destination), precision='FP16 neural blocks / FP32 box math',
                    converted_nodes=dict(collections.Counter(n.op_type for n in model.graph.node if n.name in selected)),
                    fp16_initializer_count=len(half_initializers), bytes=destination.stat().st_size,
                    input_output='Original FP32 images/boxes/scores; int64 labels',
                    preserved='Original normalization, resize geometry (including float64 shape calculations), anchors, box decode, ROIAlign, softmax, thresholds and NMS remain at original types.')
    return metadata
