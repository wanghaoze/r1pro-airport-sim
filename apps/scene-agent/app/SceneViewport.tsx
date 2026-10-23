"use client";
import {useEffect,useRef,useState} from "react";
import * as THREE from "three";
import {GLTFLoader} from "three/addons/loaders/GLTFLoader.js";
import {OrbitControls} from "three/addons/controls/OrbitControls.js";
import {RoomEnvironment} from "three/addons/environments/RoomEnvironment.js";
import {DEFAULT_COLORS,type Room} from "@/lib/core";

const VIEW = {position:[2.85,1.9,1.85] as const,target:[.15,.95,-.35] as const};
export default function SceneViewport({room,grid,fit,live,liveMode=false}:{room:Room;grid:boolean;fit:number;live?:any;liveMode?:boolean}){
  const host=useRef<HTMLDivElement>(null),model=useRef<THREE.Group|null>(null),controls=useRef<OrbitControls|null>(null),gridRef=useRef<THREE.GridHelper|null>(null),current=useRef(room),currentGrid=useRef(grid);
  const liveRef=useRef(live),bindings=useRef<any>(null);liveRef.current=live;
  const [status,setStatus]=useState("Loading laboratory and robot materials…");
  current.current=room;currentGrid.current=grid;
  function apply(){
    if(!model.current)return;
    const r=current.current,robot=model.current.getObjectByName("robot"),tray=model.current.getObjectByName("tray");
    if(liveRef.current?.bodies && bindings.current){
      const b=bindings.current,C=new THREE.Matrix4().fromArray(b.basisMatrix),Ci=C.clone().invert(),poses=liveRef.current.bodies;
      const pose=(name:string)=>{const p=poses[name];if(!p)throw Error(`Native body unavailable: ${name}`);const q=p.quaternionWxyz;return new THREE.Matrix4().compose(new THREE.Vector3(...p.position as [number,number,number]),new THREE.Quaternion(q[1],q[2],q[3],q[0]),new THREE.Vector3(1,1,1));};
      try {
        const B=pose("base_link"),Bi=B.clone().invert();
        for(const link of b.robotMeshes){if(!model.current.getObjectByName(link.meshName))throw Error(`Asset body unavailable: ${link.meshName}`);pose(link.bodyName);}
        if(robot){robot.matrixAutoUpdate=false;robot.matrix.copy(C).multiply(B).multiply(Ci);}
        for(const link of b.robotMeshes){const node=model.current.getObjectByName(link.meshName)!;node.matrixAutoUpdate=false;node.matrix.copy(C).multiply(Bi).multiply(pose(link.bodyName)).multiply(new THREE.Matrix4().fromArray(link.inverseBindMatrix)).multiply(Ci);}
        if(tray){tray.matrixAutoUpdate=false;tray.matrix.copy(C).multiply(pose("tray_0")).multiply(Ci);}
        model.current.updateMatrixWorld(true);setStatus("");
      }catch(e){setStatus(e instanceof Error?e.message:"Live pose unavailable");}
      return;
    }
    if(robot){robot.position.set(r.robot_base_pose[0],0,-r.robot_base_pose[1]);robot.rotation.y=r.robot_base_pose[2];}
    if(tray){tray.position.set(r.tray_pose[0],r.tray_pose[2],-r.tray_pose[1]);tray.rotation.y=r.tray_pose[3];}
    model.current.traverse(o=>{
      if(!(o instanceof THREE.Mesh)||!o.userData.editableColor)return;
      // The cream tray lettering is a distinct source mesh, not its paint surface.
      if(o.name==="tray_0__tray_0_visual")return;
      const kind=o.userData.editableColor as "robot"|"tray",shade=kind==="robot"?r.robot_color:r.tray_color;
      (Array.isArray(o.material)?o.material:[o.material]).forEach(m=>{
        if(!(m instanceof THREE.MeshStandardMaterial))return;
        if(shade.toUpperCase()===DEFAULT_COLORS[kind])m.color.copy(m.userData.sourceColor);
        else m.color.set(shade);
      });
    });
  }
  useEffect(()=>{
    if(!host.current)return;
    let renderer:THREE.WebGLRenderer;
    try{renderer=new THREE.WebGLRenderer({antialias:true});}catch{setStatus("WebGL is unavailable. Scene parameters and chat remain usable.");return;}
    let disposed=false,frame=0;
    const scene=new THREE.Scene();scene.background=new THREE.Color("#c7cac7");
    const camera=new THREE.PerspectiveCamera(48,1,.03,40);camera.position.set(...VIEW.position);
    renderer.setPixelRatio(Math.min(devicePixelRatio,2));renderer.shadowMap.enabled=true;renderer.shadowMap.type=THREE.PCFSoftShadowMap;
    renderer.outputColorSpace=THREE.SRGBColorSpace;renderer.toneMapping=THREE.ACESFilmicToneMapping;renderer.toneMappingExposure=.75;
    host.current.appendChild(renderer.domElement);
    const orbit=new OrbitControls(camera,renderer.domElement);controls.current=orbit;orbit.target.set(...VIEW.target);orbit.enableDamping=true;orbit.maxPolarAngle=Math.PI*.49;orbit.minDistance=1;orbit.maxDistance=12;
    // Neutral indoor reflections retain the original silver metal finish.
    const pmrem=new THREE.PMREMGenerator(renderer),environmentScene=new RoomEnvironment(),environment=pmrem.fromScene(environmentScene,.04);
    scene.environment=environment.texture;scene.environmentIntensity=.4;environmentScene.dispose();pmrem.dispose();
    scene.add(new THREE.HemisphereLight(0xffffff,0x808078,.8));
    const light=new THREE.DirectionalLight(0xfffaf2,1.4);light.position.set(1.8,2.65,1.7);light.target.position.set(.1,.6,-.3);light.castShadow=true;
    light.shadow.mapSize.set(2048,2048);light.shadow.camera.left=-4;light.shadow.camera.right=4;light.shadow.camera.top=4;light.shadow.camera.bottom=-4;light.shadow.camera.near=.05;light.shadow.camera.far=12;light.shadow.bias=-.00015;light.shadow.normalBias=.015;scene.add(light,light.target);
    const fill=new THREE.DirectionalLight(0xf0f5ff,.3);fill.position.set(-1,2.5,-2.2);scene.add(fill);
    const lines=new THREE.GridHelper(12,48,0x6c767f,0xa2aaa9);lines.position.y=.006;lines.visible=currentGrid.current;gridRef.current=lines;scene.add(lines);
    function release(root:THREE.Object3D){root.traverse(o=>{if(o instanceof THREE.Mesh){o.geometry.dispose();(Array.isArray(o.material)?o.material:[o.material]).forEach(m=>m.dispose());}});}
    new GLTFLoader().load("/assets/r1pro-scene.glb",gltf=>{
      const root=gltf.scene;if(disposed){release(root);return;}
      root.traverse(o=>{if(o instanceof THREE.Mesh){o.castShadow=true;o.receiveShadow=true;o.material=Array.isArray(o.material)?o.material.map(m=>m.clone()):o.material.clone();
        (Array.isArray(o.material)?o.material:[o.material]).forEach(m=>{if(m instanceof THREE.MeshStandardMaterial){m.userData.sourceColor=m.color.clone();if(m.transparent)o.castShadow=false;}});
      }});
      // Keep the source laboratory: floor, walls, doors, monitors and chairs.
      scene.add(root);model.current=root;apply();setStatus("");
      fetch("/assets/r1pro-bindings.json").then(r=>r.json()).then(b=>{if(!disposed){bindings.current=b;apply();}}).catch(()=>{if(liveMode)setStatus("Native pose binding could not load");});
    },undefined,()=>{if(!disposed)setStatus("Scene could not load. Refresh to retry.");});
    const resize=new ResizeObserver(()=>{if(!host.current)return;const {width,height}=host.current.getBoundingClientRect();renderer.setSize(width,height);camera.aspect=width/Math.max(height,1);camera.updateProjectionMatrix();});resize.observe(host.current);
    function tick(){orbit.update();renderer.render(scene,camera);frame=requestAnimationFrame(tick);}tick();
    return()=>{disposed=true;cancelAnimationFrame(frame);resize.disconnect();orbit.dispose();release(scene);lines.geometry.dispose();(lines.material as THREE.Material).dispose();light.shadow.map?.dispose();environment.dispose();renderer.dispose();renderer.domElement.remove();model.current=null;controls.current=null;gridRef.current=null;};
  },[]);
  useEffect(()=>apply(),[room,live]);
  useEffect(()=>{if(gridRef.current)gridRef.current.visible=grid;},[grid]);
  useEffect(()=>{const c=controls.current;if(c){c.object.position.set(...VIEW.position);c.target.set(...VIEW.target);c.update();}},[fit]);
  return <div className="viewport" ref={host} aria-label="Laboratory 3D preview with original materials">{status&&<div className="load-message">{status}</div>}<div className="viewport-caption"><span className="live-dot"/> {liveMode?"Live policy view":"Laboratory scene"} <span>{liveMode?(live?.bodies?"· Measured PhysX poses on source geometry":"· Waiting for native poses; initial preview"):"· Original materials / static preview"}</span></div><div className="axis-key"><b>Z</b><span>Y</span><em>X</em></div><div className="orbit-help">Drag to orbit · Scroll to zoom · Right-drag to pan</div></div>;
}
