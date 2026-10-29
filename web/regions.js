'use strict';
const RegionGeometry = {
  contains(rect, point) { return point[0]>=rect[0] && point[0]<=rect[2] && point[1]>=rect[1] && point[1]<=rect[3]; },
  move(rect, dx, dy, width, height) {
    dx=Math.max(-rect[0],Math.min(width-rect[2],dx));
    dy=Math.max(-rect[1],Math.min(height-rect[3],dy));
    return [rect[0]+dx,rect[1]+dy,rect[2]+dx,rect[3]+dy].map(Math.round);
  },
  hit(regions, disabled, point, chosen) {
    const keys=Object.keys(regions).filter(k=>!disabled.includes(k));
    if(keys.includes(chosen)&&this.contains(regions[chosen],point))return chosen;
    return keys.reverse().find(k=>this.contains(regions[k],point))||null;
  },
  union(a,b) { return [Math.min(a[0],b[0]),Math.min(a[1],b[1]),Math.max(a[2],b[2]),Math.max(a[3],b[3])]; }
};
if(typeof module!=='undefined')module.exports=RegionGeometry;
