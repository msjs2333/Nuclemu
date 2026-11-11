/* Apparatus symbols share a 100 × 96 drawing space. Their electrical and
   particle connections are separate and come from the course definition. */
const ink = "#394354";
const accent = "#3859d9";
const particle = "#bb5735";
const metal = ["#fbfcff", "#c4cbd7", "#8a98ac"];
const dark = ["#667389", "#465369", "#29334a"];

function line(g, points, color = ink, weight = 1.2) {
  g.beginPath();
  points.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y));
  g.strokeStyle = color;
  g.lineWidth = weight;
  g.stroke();
}

function face(g, points, color) {
  g.beginPath();
  points.forEach(([x, y], i) => i ? g.lineTo(x, y) : g.moveTo(x, y));
  g.closePath();
  g.fillStyle = color;
  g.fill();
  g.strokeStyle = ink;
  g.lineWidth = 1;
  g.stroke();
}

function chassis(g, x, y, w, h, d, colors = metal) {
  const [top, front, side] = colors, rise = d * 0.48;
  face(g, [[x,y],[x+d,y-rise],[x+w+d,y-rise],[x+w,y]], top);
  face(g, [[x+w,y],[x+w+d,y-rise],[x+w+d,y+h-rise],[x+w,y+h]], side);
  face(g, [[x,y],[x+w,y],[x+w,y+h],[x,y+h]], front);
}

function ellipse(g, x, y, rx, ry, fill) {
  g.beginPath(); g.ellipse(x, y, rx, ry, 0, 0, 2*Math.PI);
  g.fillStyle = fill; g.fill();
  g.strokeStyle = ink; g.lineWidth = 1; g.stroke();
}

function stand(g) {
  chassis(g,-30,24,54,5,9,dark);
  chassis(g,-5,3,9,20,5);
}

function source(g) {
  stand(g);
  chassis(g,-23,-21,36,29,8,dark);
  chassis(g,-20,-17,28,20,2);
  for(const x of [-16,-11,-6]) line(g,[[x,-14],[x,-5]],"#6c7a91",1);
  ellipse(g,20,-7,8,15,"#aab4c3");
  ellipse(g,21,-7,6,12,"#515e72");
  ellipse(g,22,-7,3.2,6,"#db9665");
  for(const x of [-17,4]) ellipse(g,x,0,1,1,"#626e83");
}

function foil(g) {
  stand(g);
  // Two side clamps, a foil surface and a retaining bar on the sample carrier.
  chassis(g,-20,-28,34,43,6);
  chassis(g,-16,-23,26,31,2,["#fbfcff","#d9dfe8","#a8b5c7"]);
  line(g,[[-11,-14],[-2,-19]],"#f8fafb",2);
  line(g,[[-13,-5],[4,-16]],"#f0f3fa",2);
  chassis(g,-23,-30,6,47,4,dark);
  chassis(g,12,-30,6,47,4,dark);
  chassis(g,-23,12,41,5,4,dark);
  for(const x of [-20,15]) for(const y of [-25,8]) ellipse(g,x,y,1.2,1.2,"#bac5d3");
}

function detector(g, spectrum) {
  stand(g);
  if(spectrum) {
    // Silicon detector head, sensitive window and a rear feedthrough.
    chassis(g,-24,-20,43,26,10);
    ellipse(g,-22,-7,10,14,"#737c8c");
    ellipse(g,-23,-7,7,11,"#bd9274");
    ellipse(g,-23,-7,4,7,"#937964");
    chassis(g,29,-10,8,6,3,dark);
  } else {
    // Counting head with a longer cylindrical housing and thin entrance window.
    chassis(g,-24,-17,51,20,4,dark);
    ellipse(g,26,-7,5,10,"#6b7485");
    ellipse(g,-24,-7,6,10,"#cbd2dc");
    for(const x of [-16,-12,15,19]) line(g,[[x,-16],[x,2]],"#92a0b4");
    chassis(g,30,-9,7,4,2);
  }
}

function instrument(g, kind) {
  chassis(g,-35,-25,60,38,12);
  chassis(g,-39,-9,4,4,2,dark);
  chassis(g,-27,12,7,3,3,dark);
  chassis(g,16,12,7,3,3,dark);
  for(let x=-14;x<=14;x+=4) line(g,[[x,-26],[x+6,-29]],"#939daf",.7);
  g.fillStyle="#252d45"; g.fillRect(-29,-19,39,22);
  if(kind==="spectrum") {
    for(let x=-24;x<9;x+=8) line(g,[[x,-18],[x,2]],"#47516a",.65);
    for(let y=-15;y<3;y+=6) line(g,[[-28,y],[8,y]],"#47516a",.65);
    line(g,[[-26,0],[-20,0],[-17,-9],[-15,0],[-8,0],[-5,-15],[-3,0],[1,0],[3,-7],[5,0],[7,0]],"#b8c7ff",1.5);
  } else if(kind==="counter") {
    for(let x=-24;x<6;x+=6) {
      g.strokeStyle="#46516b";g.lineWidth=.7;g.strokeRect(x,-13,3.5,10);
      line(g,[[x,-8],[x+3.5,-8]],"#e9c5ac",1.8);
    }
  }
  ellipse(g,17,-12,4,4,"#73809b");
  ellipse(g,17,2,2,2,"#253148");
  for(let x=-28;x<-4;x+=4) line(g,[[x,8],[x+2,8]],"#566781",1);
}

function glyph(g, part, devices) {
  const kind=devices.find(device=>device.id===part.device)?.kind;
  switch(part.kind) {
    case "source": source(g); break;
    case "foil": foil(g); break;
    case "detector": detector(g,kind==="spectrum"); break;
    case "instrument": instrument(g,kind); break;
    default: chassis(g,-23,-15,40,27,8);
  }
}

function prepare(canvas) {
  const width=canvas.clientWidth, height=canvas.clientHeight;
  if(!width || !height) return;
  const dpr=window.devicePixelRatio||1;
  const w=Math.round(width*dpr), h=Math.round(height*dpr);
  if(canvas.width!==w) canvas.width=w;
  if(canvas.height!==h) canvas.height=h;
  const g=canvas.getContext("2d");
  g.setTransform(dpr,0,0,dpr,0,0);
  g.clearRect(0,0,width,height);
  return {g,width,height};
}

function connect(g, start, end, kind, detour) {
  const dx=end.x-start.x, dir=dx>=0?1:-1;
  const x1=start.x+dir*(dir>0?start.right:start.left), x2=end.x-dir*(dir>0?end.left:end.right);
  const color=kind==="particle"?particle:accent;
  const points=[[x1,start.y]];
  if(detour) {
    const bend=Math.min(start.y,end.y)-Math.max(start.left,end.left)*1.15;
    points.push([x1+dir*4,start.y],[x1+dir*4,bend],[x2-dir*6,bend],[x2-dir*6,end.y]);
  } else if(Math.abs(end.y-start.y)>1) {
    points.push([(x1+x2)/2,start.y],[(x1+x2)/2,end.y]);
  }
  points.push([x2,end.y]);
  g.save(); g.setLineDash(kind==="particle"?[4,3]:[]); line(g,points,color,1.6);
  g.setLineDash([]);line(g,[[x2-dir*4,end.y-3],[x2,end.y],[x2-dir*4,end.y+3]],color,1.6);g.restore();
}

function routes(g, edges, positions, labels=false) {
  for(const edge of edges) {
    const src=positions.get(edge.source), dst=positions.get(edge.target);
    if(!src || !dst) continue;
    const detour=[...positions.values()].some(p=>p.x>Math.min(src.x,dst.x) && p.x<Math.max(src.x,dst.x));
    connect(g,src,dst,edge.kind,detour);
    if(labels && !detour && dst.x>src.x && edge.label) {
      const start=src.x+src.right, end=dst.x-dst.left;
      g.save();
      g.font='12px "Segoe UI", "Microsoft YaHei UI", sans-serif';
      if(end-start>g.measureText(edge.label).width+8) {
        g.fillStyle=edge.kind==="particle"?"#884529":"#365099";
        g.textAlign="center"; g.fillText(edge.label,(start+end)/2,src.y-9);
      }
      g.restore();
    }
  }
}

function symbolScale(width,height) {
  return Math.min(width/100,height/87,3.3);
}

// Horizontal limits of each symbol at beam height in the drawing space.
const ports={source:[23,29], foil:[23,22], detector:[32,40], instrument:[39,37]};
function placement(kind,x,y,scale) {
  const [left,right]=ports[kind]||[32,32];
  return {x,y,left:(left+1)*scale,right:(right+1)*scale};
}

export function drawApparatus(canvas,parts,devices,connections=[]) {
  const surface=prepare(canvas);if(!surface||!parts.length)return;
  const {g,width,height}=surface;
  const step=width/parts.length, scale=symbolScale(step,height);
  const positions=new Map(parts.map((p,i)=>[p.id,placement(p.kind,step*(i+.5),height*.5,scale)]));
  routes(g,connections,positions);
  for(const part of parts) {
    const {x,y}=positions.get(part.id);
    g.save();g.translate(x,y+7*scale);g.scale(scale,scale);glyph(g,part,devices);g.restore();
  }
}

// Draw into an absolutely positioned canvas sharing the apparatus container
// with the keyboard-selectable component buttons.
export function drawConnections(canvas,connections) {
  const surface=prepare(canvas);if(!surface)return;
  const origin=canvas.getBoundingClientRect(), positions=new Map();
  for(const button of canvas.parentElement.querySelectorAll("button[data-part]")) {
    const art=button.querySelector("canvas");if(!art)continue;
    const rect=art.getBoundingClientRect();
    positions.set(button.dataset.part,placement(button.dataset.kind,rect.left-origin.left+rect.width/2,
      rect.top-origin.top+rect.height/2,symbolScale(rect.width,rect.height)));
  }
  routes(surface.g,connections,positions,true);
}

export const margin={left:62,right:27,top:30,bottom:43};
export function channelAt(canvas,event,n) {
  const rect=canvas.getBoundingClientRect();
  const t=(event.clientX-rect.left-canvas.clientLeft-margin.left)/Math.max(1,canvas.clientWidth-margin.left-margin.right);
  return Math.max(0,Math.min(n-1,Math.round(t*(n-1))));
}

function axisTick(value) {
  if(Math.abs(value)>=1e5 || (value!==0 && Math.abs(value)<.01))return value.toExponential(1);
  return Number(value.toPrecision(4)).toString();
}

function tickSpacing(target) {
  const order=10**Math.floor(Math.log10(target));
  return [1,2,5,10].find(factor=>factor*order>=target)*order;
}

function horizontalTicks(channels,energy,width) {
  const goal=Math.max(2,Math.min(10,Math.floor(width/82)));
  const last=channels-1;
  if(last===0) return [{channel:0,label:energy?axisTick(energy(0)):"0"}];
  if(energy) {
    const start=energy(0), end=energy(last);
    if(start===end) return [{channel:0,label:axisTick(start)}];
    const step=tickSpacing(Math.abs(end-start)/goal);
    const first=Math.ceil(Math.min(start,end)/step);
    const count=Math.floor(Math.max(start,end)/step)-first+1;
    const ticks=[];
    for(let i=0;i<Math.min(count,goal+2);i++){
      const value=(first+i)*step;
      ticks.push({channel:last*(value-start)/(end-start),label:axisTick(value)});
    }
    return ticks;
  }
  const step=2**Math.max(0,Math.ceil(Math.log2(last/goal)));
  const ticks=[];
  for(let channel=0;channel<last;channel+=step) {
    if(channel && (last-channel)*width/last<42) break;
    ticks.push({channel,label:String(channel)});
  }
  ticks.push({channel:last,label:String(last)});
  return ticks;
}

export function drawSpectrum(canvas,series,n,roi,energy,label) {
  const surface=prepare(canvas);if(!surface || n<1)return;
  const {g,width,height}=surface;
  const left=margin.left,right=width-margin.right,top=margin.top,bottom=height-margin.bottom;
  if(right<=left || bottom<=top)return;
  let high=0;
  for(const item of series)if(item.divisor>0)for(const value of item.counts)high=Math.max(high,value/item.divisor);
  if(high===0)high=1;
  let yStep=tickSpacing(high/5);
  if(label==="每道计数")yStep=Math.max(yStep,1);
  const yTicks=Math.ceil(high/yStep);
  high=yTicks*yStep;
  const x=i=>left+(right-left)*i/Math.max(1,n-1);
  const y=v=>bottom-(bottom-top)*v/high;
  g.font='12px "Segoe UI", "Microsoft YaHei UI", "Microsoft YaHei", sans-serif';
  g.textAlign="left";g.fillStyle="#414b60";g.fillText(label,left,16);
  const [lo,hi]=roi;
  if(lo>0 || hi<n-1) {
    g.fillStyle="rgba(56,89,217,.065)";g.fillRect(x(lo),top,Math.max(1,x(hi)-x(lo)),bottom-top);
    line(g,[[x(lo),top],[x(lo),bottom]],"#aab9eb",1);
    line(g,[[x(hi),top],[x(hi),bottom]],"#aab9eb",1);
  }
  g.textAlign="right";g.fillStyle="#414b60";
  for(let i=0;i<=yTicks;i++) {
    const value=yStep*i, tickY=y(value);
    line(g,[[left,tickY],[right,tickY]],"#e2e6ef",1);
    g.fillText(axisTick(value),left-8,tickY+4);
  }
  const ticks=horizontalTicks(n,energy,right-left);
  for(const tick of ticks){
    if(tick.channel<=0||tick.channel>=n-1) continue;
    const column=x(tick.channel);
    line(g,[[column,top],[column,bottom]],"#e8ebf2",1);
  }
  line(g,[[left,top],[left,bottom],[right,bottom]],"#909aac",1);
  series.forEach((item,index)=>{
    if(!(item.divisor>0))return;
    g.beginPath();g.strokeStyle=index?"#c65b35":accent;
    g.lineWidth=index?1.4:1.7;g.setLineDash(index?[5,3]:[]);
    item.counts.forEach((v,i)=>i?g.lineTo(x(i),y(v/item.divisor)):g.moveTo(x(i),y(v/item.divisor)));
    g.stroke();
  });
  g.setLineDash([]);g.textAlign="center";g.fillStyle="#414b60";
  for(const tick of ticks){
    line(g,[[x(tick.channel),bottom],[x(tick.channel),bottom+4]],"#909aac");
    g.fillText(tick.label,x(tick.channel),bottom+18);
  }
  g.fillText(energy?"能量 / MeV":"道号",(left+right)/2,height-6);
}
