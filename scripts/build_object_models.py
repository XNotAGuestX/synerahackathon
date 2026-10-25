"""Rebuild the small, self-contained GLBs without Blender or additional packages.

Use --kenney-archive /path/kenney_furniture-kit.zip to restore the library subset.
The archive hash is pinned in the shared catalog; no runtime network is required.
"""

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import struct
import zipfile


ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / "final_agent/object_catalog.json"
OUTPUT = ROOT / "frontend/public/models/objects"
PALETTE = {
    "white": [0.88, 0.9, 0.9, 1], "metal": [0.56, 0.62, 0.65, 1],
    "dark": [0.14, 0.18, 0.2, 1], "wood": [0.896, 0.602, 0.393, 1],
    "blue": [0.28, 0.51, 0.64, 1], "red": [0.78, 0.18, 0.14, 1],
    "green": [0.3, 0.56, 0.4, 1], "grey": [0.32, 0.32, 0.32, 1],
}


class Model:
    def __init__(self):
        self.parts = defaultdict(lambda: {"positions": [], "normals": []})

    def triangle(self, a, b, c, material):
        u = [b[i] - a[i] for i in range(3)]
        v = [c[i] - a[i] for i in range(3)]
        n = [u[1]*v[2]-u[2]*v[1], u[2]*v[0]-u[0]*v[2], u[0]*v[1]-u[1]*v[0]]
        length = math.sqrt(sum(x*x for x in n)) or 1
        part = self.parts[material]
        part["positions"].extend([*a, *b, *c])
        part["normals"].extend([x/length for x in n] * 3)

    def box(self, x, y, z, w, h, d, material="white"):
        # y is the bottom; x/z locate the centre. Flat normals retain the kit's faceted style.
        p = [(x+sx*w/2, y+sy*h, z+sz*d/2) for sx,sy,sz in
             [(-1,0,-1),(1,0,-1),(1,1,-1),(-1,1,-1),(-1,0,1),(1,0,1),(1,1,1),(-1,1,1)]]
        for a,b,c,d in [(0,3,2,1),(4,5,6,7),(0,4,7,3),(1,2,6,5),(0,1,5,4),(3,7,6,2)]:
            self.triangle(p[a],p[b],p[c],material)
            self.triangle(p[a],p[c],p[d],material)

    def cylinder(self, x, y, z, radius, height, material="metal", segments=10):
        for i in range(segments):
            a,b = i*math.tau/segments,(i+1)*math.tau/segments
            p=(x+radius*math.cos(a),y,z+radius*math.sin(a))
            q=(x+radius*math.cos(b),y,z+radius*math.sin(b))
            r=(q[0],y+height,q[2]);s=(p[0],y+height,p[2])
            self.triangle(p,s,r,material); self.triangle(p,r,q,material)
            self.triangle((x,y,z),p,q,material)
            self.triangle((x,y+height,z),r,s,material)

    def bench(self, top=.55, material="wood"):
        self.box(0,top,0,1,.08,.7,material)
        for x in [-.4,.4]:
            for z in [-.25,.25]: self.box(x,0,z,.07,top,.07,"metal")

    def cabinet(self, material="white", drawers=0):
        self.box(0,0,0,1,1,.7,material)
        self.box(0,.08,.355,.86,.84,.02,"metal")
        for i in range(drawers or 1):
            y=.1+i*.8/(drawers or 1)
            self.box(0,y,.375,.8,.8/(drawers or 1)-.025,.02,material)
            self.box(.22,y+.08,.4,.16,.025,.025,"dark")

    def panel(self, x=0, y=.55, z=.37, w=.3, h=.2):
        self.box(x,y,z,w,h,.025,"dark")
        self.box(x,y+.035,z+.016,w*.8,h*.65,.012,"blue")

    def write(self, path):
        binary = bytearray()
        document = {"asset":{"version":"2.0","generator":"Talk to Your Building schematic generator"},
                    "scene":0,"scenes":[{"nodes":[0]}],"nodes":[{"mesh":0}],"meshes":[{"primitives":[]}],
                    "materials":[],"accessors":[],"bufferViews":[],"buffers":[]}
        for material,part in self.parts.items():
            material_index=len(document["materials"])
            document["materials"].append({"name":material,"pbrMetallicRoughness":{
                "baseColorFactor":PALETTE[material],"metallicFactor":0,"roughnessFactor":1}})
            attrs={}
            for attribute,key in [("POSITION","positions"),("NORMAL","normals")]:
                values=part[key]; offset=len(binary)
                binary.extend(struct.pack('<'+'f'*len(values),*values))
                view=len(document["bufferViews"])
                document["bufferViews"].append({"buffer":0,"byteOffset":offset,"byteLength":len(values)*4,"target":34962})
                accessor={"bufferView":view,"componentType":5126,"count":len(values)//3,"type":"VEC3"}
                if attribute=="POSITION":
                    accessor["min"]=[min(values[i::3]) for i in range(3)]
                    accessor["max"]=[max(values[i::3]) for i in range(3)]
                attrs[attribute]=len(document["accessors"]);document["accessors"].append(accessor)
            document["meshes"][0]["primitives"].append({"attributes":attrs,"material":material_index})
        document["buffers"]=[{"byteLength":len(binary)}]
        encoded=json.dumps(document,separators=(',',':')).encode()
        encoded+=b' '*((-len(encoded))%4)
        binary+=b'\0'*((-len(binary))%4)
        path.write_bytes(struct.pack('<III',0x46546c67,2,28+len(encoded)+len(binary))+
                         struct.pack('<II',len(encoded),0x4e4f534a)+encoded+
                         struct.pack('<II',len(binary),0x004e4942)+binary)


def schematic(t):
    m=Model()
    if t=="unknown":
        m.box(0,0,0,1,1,1,"grey")
    elif t in {"chemical_cabinet","filing_cabinet","locker","tool_cabinet","dishwasher","curing_oven","ups_unit","electrical_panel","hand_dryer","defibrillator"}:
        m.cabinet("blue" if t in {"tool_cabinet","locker"} else "white",4 if t in {"filing_cabinet","tool_cabinet"} else 0)
        if t=="dishwasher": m.panel(y=.85,w=.7,h=.08)
        elif t=="curing_oven": m.panel(y=.3,w=.65,h=.5)
        elif t=="defibrillator":
            m.box(0,.2,.405,.14,.55,.025,"green");m.box(0,.4,.425,.55,.14,.025,"green")
        elif t=="chemical_cabinet": m.box(0,.5,.4,.25,.2,.025,"red")
        elif t=="hand_dryer": m.box(0,0,.4,.45,.12,.12,"dark")
        elif t=="ups_unit": m.panel(w=.5,h=.15)
    elif t in {"assembly_station","packing_station","inspection_bench","lab_bench","workbench","reception_desk","soldering_station","oscilloscope_station"}:
        m.bench()
        if t=="reception_desk":
            m.box(0,0,.28,1,.7,.08,"wood");m.box(0,.7,.28,1,.08,.3,"white")
        elif t in {"assembly_station","packing_station"}:
            for x in [-.42,.42]: m.box(x,.6,-.28,.05,.4,.05,"metal")
            m.box(0,.9,-.28,1,.06,.4,"wood")
        elif t in {"soldering_station","oscilloscope_station"}:
            m.box(0,.63,0,.45,.3,.35,"white");m.panel(y=.68,z=.19,w=.32,h=.16)
        elif t=="inspection_bench": m.box(.2,.63,0,.35,.12,.3,"blue")
        elif t=="lab_bench": m.cylinder(-.3,.63,0,.05,.15,"blue")
    elif t in {"server_rack","vending_machine","atm","powder_station","fume_hood","industrial_3d_printer","3d_printer","cnc_mill","cnc_lathe","laser_cutter","injection_moulding_machine"}:
        m.cabinet("metal")
        if t=="server_rack":
            for i in range(8):
                m.box(0,.08+i*.1,.39,.8,.07,.03,"dark");m.box(.3,.1+i*.1,.41,.035,.025,.01,"green")
        elif t=="vending_machine":
            m.panel(x=-.12,y=.2,w=.58,h=.65)
            for y in [.3,.5,.7]:
                for x in [-.3,-.1,.1]:m.box(x,y,.41,.1,.06,.015,"wood")
            m.panel(x=.34,y=.62,w=.15,h=.22)
        elif t=="atm": m.panel(y=.55,w=.55,h=.3);m.box(0,.2,.42,.4,.05,.1,"dark")
        else:
            m.panel(x=-.08,y=.25,w=.68,h=.55)
            if t in {"3d_printer","industrial_3d_printer","cnc_mill","cnc_lathe"}:
                m.box(-.08,.3,.43,.04,.4,.03,"metal");m.box(-.08,.45,.44,.4,.05,.03,"metal")
            if t in {"fume_hood","powder_station"}: m.box(0,.9,0,1.1,.15,.8,"white")
            if t=="injection_moulding_machine":m.cylinder(-.45,.9,0,.1,.15,"blue")
    elif t in {"whiteboard","projector_screen"}:
        m.box(0,0,0,1,1,.035,"metal");m.box(0,.035,.025,.94,.93,.02,"white")
        m.box(0,.02,.06,1,.025,.1,"dark")
    elif t in {"printer","multifunction_printer","projector"}:
        m.box(0,0,0,1,.65,.7,"white")
        if t=="projector":
            m.box(-.25,.15,.37,.25,.25,.08,"dark");m.box(-.25,.18,.42,.18,.18,.02,"blue")
        else:
            m.box(0,.66,-.08,.8,.06,.5,"metal");m.box(0,.3,.37,.65,.12,.05,"dark")
            m.box(0,.72,-.1,.65,.02,.38,"white")
            if t=="multifunction_printer":m.box(0,-.4,0,1,.4,.7,"metal")
    elif t in {"forklift","pallet_jack"}:
        m.box(0,.12,0,.7,.22,.7,"blue")
        for x in [-.24,.24]:m.box(x,.1,.65,.1,.06,.9,"metal")
        for x in [-.35,.35]:
            for z in [-.25,.25]: m.box(x,0,z,.12,.23,.23,"dark")
        if t=="forklift":
            for x in [-.25,.25]: m.box(x,.3,-.25,.05,.65,.05,"metal")
            m.box(0,.92,-.1,.75,.07,.65,"metal")
            for x in [-.24,.24]:m.box(x,.2,.35,.06,.8,.06,"dark")
            m.box(0,.35,-.1,.4,.13,.35,"dark")
        else: m.box(0,.25,-.3,.06,.7,.06,"dark");m.box(0,.92,-.3,.45,.05,.05,"dark")
    elif t in {"pallet_rack","lecture_seating_row"}:
        if t=="pallet_rack":
            for x in [-.45,.45]:
                for z in [-.3,.3]:m.box(x,0,z,.06,1,.06,"blue")
            for y in [.05,.45,.85]:m.box(0,y,0,1,.06,.7,"wood")
        else:
            for x in [-.34,0,.34]:
                m.box(x,.3,0,.28,.07,.45,"wood");m.box(x,.35,-.2,.28,.4,.06,"blue")
                m.box(x,0,0,.06,.3,.06,"metal")
    elif t=="lectern":
        m.box(0,0,0,.65,.08,.5,"wood");m.box(0,.08,0,.13,.8,.13,"metal");m.box(0,.88,0,1,.08,.7,"wood")
    elif t=="fire_extinguisher":
        m.cylinder(0,0,0,.22,.8,"red");m.cylinder(0,.8,0,.1,.1,"metal")
        m.box(0,.9,0,.45,.06,.1,"dark");m.box(.3,.35,0,.045,.5,.05,"dark")
    elif t in {"boiler","compressor","water_dispenser","eyewash_station","welding_station"}:
        m.cylinder(0,0,0,.3,.7,"white")
        if t=="boiler":m.panel(y=.3,z=.31,w=.3,h=.2);m.cylinder(0,.7,0,.1,.3)
        elif t=="compressor":m.box(0,.72,0,.5,.25,.35,"blue")
        elif t=="water_dispenser":
            m.cylinder(0,.7,0,.25,.3,"blue");m.box(0,.3,.3,.25,.16,.1,"dark")
        elif t=="eyewash_station":
            m.cylinder(0,.7,0,.4,.12,"metal");m.cylinder(-.15,.82,0,.03,.15,"green");m.cylinder(.15,.82,0,.03,.15,"green")
        else:
            m.box(-.38,0,0,.35,.3,.5,"blue");m.box(0,.8,0,.15,.07,.15,"dark")
    elif t=="forklift_charging_station":
        m.cabinet("blue");m.panel();m.box(.58,.1,0,.06,.7,.08,"dark")
    elif t=="microscope":
        m.box(0,0,0,.7,.1,.6,"white");m.box(-.2,.1,-.15,.12,.65,.12,"metal")
        m.box(0,.35,0,.6,.06,.4,"dark");m.cylinder(0,.5,0,.08,.4,"white")
        m.box(0,.86,.12,.13,.08,.3,"dark")
    elif t in {"drill_press","milling_machine"}:
        m.box(0,0,0,.8,.1,.7,"metal");m.cylinder(0,.1,-.22,.07,.8)
        m.box(0,.4,0,.7,.08,.5,"blue");m.box(0,.8,-.04,.45,.18,.5,"blue")
        m.cylinder(0,.66,.13,.035,.16,"dark")
    elif t in {"conveyor","coordinate_measuring_machine","waterjet_cutter","press_brake","robot_cell"}:
        m.bench(material="metal")
        if t=="conveyor":
            for i in range(10):m.box(0,.64,-.3+i*.065,.92,.03,.035,"dark")
        elif t=="press_brake":
            for x in [-.4,.4]:m.box(x,0,0,.15,1,.6,"blue")
            m.box(0,.75,0,1,.2,.5,"blue");m.box(0,.7,.1,.8,.045,.08,"dark")
        elif t=="robot_cell":
            for x in [-.46,.46]:
                for z in [-.3,.3]:m.box(x,0,z,.04,1,.04,"blue")
            m.box(0,.96,0,1,.04,.7,"blue");m.cylinder(0,.64,0,.12,.12,"wood")
            m.box(.08,.75,0,.15,.2,.15,"wood");m.box(.22,.9,0,.4,.1,.1,"wood")
        else:
            for x in [-.4,.4]:m.box(x,.6,0,.08,.4,.15,"white")
            m.box(0,.9,0,.9,.1,.17,"white");m.box(0,.72,0,.05,.18,.05,"dark")
    elif t=="hvac_unit":
        m.cabinet("metal")
        for x in [-.25,.25]:
            m.box(x,.2,.39,.4,.5,.02,"dark")
            for i in range(6):m.box(x,.23+i*.075,.41,.36,.015,.02,"metal")
    else:
        raise ValueError(f"No intentional schematic for {t}; unknown types must use unknown.glb.")
    return m


def glb_stats(path):
    data=path.read_bytes()
    magic,version,length=struct.unpack_from('<III',data)
    if magic!=0x46546c67 or version!=2 or length!=len(data): raise ValueError(f"Invalid GLB: {path}")
    json_length=struct.unpack_from('<I',data,12)[0]
    doc=json.loads(data[20:20+json_length])
    if doc.get('images') or any(b.get('uri') for b in doc.get('buffers',[])):
        raise ValueError(f"Expected a texture-free, self-contained model: {path}")
    triangles=sum(doc['accessors'][p['indices']]['count']//3 if 'indices' in p else doc['accessors'][p['attributes']['POSITION']]['count']//3
                  for mesh in doc['meshes'] for p in mesh['primitives'])
    if triangles>2000 or len(data)>128*1024: raise ValueError(f"Model exceeds budget: {path}")
    return {'bytes':len(data),'triangles':triangles}


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--kenney-archive',type=Path)
    args=parser.parse_args()
    catalog=json.loads(CATALOG.read_text())
    OUTPUT.mkdir(parents=True,exist_ok=True)
    archive=None
    if args.kenney_archive:
        expected=catalog['sources']['kenney_furniture']['archive_sha256']
        if hashlib.sha256(args.kenney_archive.read_bytes()).hexdigest()!=expected: raise ValueError('Kenney archive checksum differs.')
        archive=zipfile.ZipFile(args.kenney_archive)
        (OUTPUT/'KENNEY_LICENSE.txt').write_bytes(archive.read('License.txt'))
    schematic('unknown').write(OUTPUT/'unknown.glb')
    stats=[]
    try:
        for t,entry in catalog['objects'].items():
            path=OUTPUT/Path(entry['model_path']).name
            if entry['model_kind']=='placeholder': continue
            if entry['model_source']=='kenney_furniture':
                if archive: path.write_bytes(archive.read('Models/GLTF format/'+entry['source_asset']))
                elif not path.exists(): raise ValueError('Restore missing Kenney models with --kenney-archive.')
            else: schematic(t).write(path)
            stats.append(glb_stats(path))
    finally:
        if archive:archive.close()
    print(f"{len(stats)} object models; {sum(s['bytes'] for s in stats):,} bytes; max {max(s['triangles'] for s in stats)} triangles/model.")


if __name__=='__main__':main()
