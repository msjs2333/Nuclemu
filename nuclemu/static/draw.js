/* Apparatus symbols share a 100 × 96 drawing space. Their electrical and
   particle connections are separate and come from the course definition. */
const ink = "#394951";
const accent = "#086f79";
const particle = "#a45d29";
const metal = ["#fcfdfe", "#becbd1", "#889ba6"];
const dark = ["#687b88", "#435864", "#293b46"];

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
  chassis(g,-24,-23,40,33,10,dark);
  chassis(g,-21,-20,33,26,3);
  ellipse(g,0,-7,9,11,"#716e61");
  ellipse(g,0,-7,4,5,"#ebb66c");
  for(const x of [-17,8]) for(const y of [-16,3]) ellipse(g,x,y,1,1,"#637782");
}

function foil(g) {
  stand(g);
  // Two side clamps, a foil surface and a retaining bar on the sample carrier.
  chassis(g,-20,-28,34,43,6);
  chassis(g,-16,-23,26,31,2,["#fafcfb","#d6dfe0","#a3b7bf"]);
  line(g,[[-11,-14],[-2,-19]],"#f8fafb",2);
  line(g,[[-13,-5],[4,-16]],"#eff5f7",2);
  chassis(g,-23,-30,6,47,4,dark);
  chassis(g,12,-30,6,47,4,dark);
  chassis(g,-23,12,41,5,4,dark);
}

function detector(g, spectrum) {
  stand(g);
  if(spectrum) {
    // Silicon detector head, sensitive window and a rear feedthrough.
    chassis(g,-24,-20,43,26,10);
    ellipse(g,-22,-7,10,14,"#6d8086");
    ellipse(g,-23,-7,7,11,"#c7a375");
    ellipse(g,-23,-7,4,7,"#897659");
    chassis(g,29,-14,8,6,3,dark);
  } else {
    // Counting head with a longer cylindrical housing and thin entrance window.
    chassis(g,-24,-17,51,20,4,dark);
    ellipse(g,26,-7,5,10,"#6c7c83");
    ellipse(g,-24,-7,6,10,"#cad5d8");
    for(const x of [-16,-12,15,19]) line(g,[[x,-16],[x,2]],"#91a6af");
    chassis(g,30,-9,7,4,2);
  }
}

function instrument(g, kind) {
  chassis(g,-33,-25,58,38,10);
  chassis(g,-27,12,7,3,3,dark);
  chassis(g,16,12,7,3,3,dark);
  g.fillStyle="#273d49"; g.fillRect(-28,-19,37,22);
  if(kind==="spectrum") {
    line(g,[[-26,0],[-20,0],[-17,-9],[-15,0],[-8,0],[-5,-15],[-3,0],[1,0],[3,-7],[5,0],[7,0]],"#9ee3da",1.5);
  } else if(kind==="counter") {
    for(let x=-23;x<6;x+=6) line(g,[[x,-8],[x+3.5,-8]],"#9ee3da",2);
  }
  ellipse(g,17,-12,4,4,"#708996");
  ellipse(g,17,2,2,2,"#243d47");
  for(let x=-28;x<-4;x+=4) line(g,[[x,8],[x+2,8]],"#536b76",1);
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
  const x1=start.x+dir*start.half, x2=end.x-dir*end.half;
  const color=kind==="particle"?particle:accent;
  const points=[[x1,start.y]];
  if(detour) {
    const bend=Math.min(start.y,end.y)-Math.max(start.half,end.half)*0.93;
    points.push([x1+dir*4,start.y],[x1+dir*4,bend],[x2-dir*6,bend],[x2-dir*6,end.y]);
  } else if(Math.abs(end.y-start.y)>1) {
    points.push([(x1+x2)/2,start.y],[(x1+x2)/2,end.y]);
  }
  points.push([x2,end.y]);
  g.save(); g.setLineDash(kind==="particle"?[4,3]:[]); line(g,points,color,1.6);
  g.setLineDash([]);line(g,[[x2-dir*4,end.y-3],[x2,end.y],[x2-dir*4,end.y+3]],color,1.6);g.restore();
}

function routes(g, edges, positions) {
  for(const edge of edges) {
    const src=positions.get(edge.source), dst=positions.get(edge.target);
    if(!src || !dst) continue;
    const detour=[...positions.values()].some(p=>p.x>Math.min(src.x,dst.x) && p.x<Math.max(src.x,dst.x));
    connect(g,src,dst,edge.kind,detour);
  }
}

export function drawApparatus(canvas,parts,devices,connections=[]) {
  const surface=prepare(canvas);if(!surface||!parts.length)return;
  const {g,width,height}=surface;
  const step=width/parts.length, scale=Math.min(step/108,height/87,2);
  const positions=new Map(parts.map((p,i)=>[p.id,{x:step*(i+.5),y:height*.5,half:scale*39}]));
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
    positions.set(button.dataset.part,{x:rect.left-origin.left+rect.width/2,y:rect.top-origin.top+rect.height*.5,half:Math.min(rect.width/108,rect.height/87,2)*39});
  }
  routes(surface.g,connections,positions);
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

export function drawSpectrum(canvas,series,n,roi,energy,label) {
  const surface=prepare(canvas);if(!surface || n<1)return;
  const {g,width,height}=surface;
  const left=margin.left,right=width-margin.right,top=margin.top,bottom=height-margin.bottom;
  if(right<=left || bottom<=top)return;
  let high=0;
  for(const item of series)if(item.divisor>0)for(const value of item.counts)high=Math.max(high,value/item.divisor);
  if(high===0)high=1;
  const magnitude=10**Math.floor(Math.log10(high/5));
  let yStep=[1,2,5,10].find(step=>step*magnitude>=high/5)*magnitude;
  if(label==="每道计数")yStep=Math.max(yStep,1);
  const yTicks=Math.ceil(high/yStep);
  high=yTicks*yStep;
  const x=i=>left+(right-left)*i/Math.max(1,n-1);
  const y=v=>bottom-(bottom-top)*v/high;
  g.font='12px "Segoe UI", "Microsoft YaHei", sans-serif';
  g.fillStyle="#334650";g.fillText(label,left,16);
  const [lo,hi]=roi;
  g.fillStyle="rgba(8,111,121,.08)";g.fillRect(x(lo),top,Math.max(1,x(hi)-x(lo)),bottom-top);
  line(g,[[x(lo),top],[x(lo),bottom]],"#9abdc2",1);
  line(g,[[x(hi),top],[x(hi),bottom]],"#9abdc2",1);
  g.textAlign="right";g.fillStyle="#334650";
  for(let i=0;i<=yTicks;i++) {
    const value=yStep*i, tickY=y(value);
    line(g,[[left,tickY],[right,tickY]],"#e3e9ec",1);
    g.fillText(axisTick(value),left-8,tickY+4);
  }
  line(g,[[left,top],[left,bottom],[right,bottom]],"#84959d",1);
  series.forEach((item,index)=>{
    if(!(item.divisor>0))return;
    g.beginPath();g.strokeStyle=index?"#996731":accent;
    g.lineWidth=index?1.4:1.7;g.setLineDash(index?[5,3]:[]);
    item.counts.forEach((v,i)=>i?g.lineTo(x(i),y(v/item.divisor)):g.moveTo(x(i),y(v/item.divisor)));
    g.stroke();
  });
  g.setLineDash([]);g.textAlign="center";g.fillStyle="#334650";
  const ticks=Math.min(Math.max(1,n-1),Math.max(1,Math.min(8,Math.floor((right-left)/75))));
  for(let i=0;i<=ticks;i++){
    const c=Math.round(i*(n-1)/ticks);
    line(g,[[x(c),bottom],[x(c),bottom+4]],"#84959d");
    g.fillText(energy?axisTick(energy(c)):String(c),x(c),bottom+18);
  }
  g.fillText(energy?"能量 / MeV":"道号",(left+right)/2,height-6);
}
