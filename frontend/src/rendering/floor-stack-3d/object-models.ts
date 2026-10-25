import * as THREE from 'three'
import { GLTFLoader } from 'three/examples/jsm/loaders/GLTFLoader.js'
import { objectVisual } from '../../domain/object-catalog'
import type { Asset, FloorPlan } from '../../domain/types'

type Part = { geometry: THREE.BufferGeometry; material: THREE.Material | THREE.Material[] }
type PlacedAsset = { asset: Asset; elevation: number }

function disposeParts(parts: Part[]) {
  const materials = new Set<THREE.Material>()
  for (const part of parts) {
    part.geometry.dispose()
    for (const material of Array.isArray(part.material) ? part.material : [part.material]) materials.add(material)
  }
  for (const material of materials) material.dispose()
}

async function loadParts(path: string): Promise<Part[]> {
  const gltf = await new GLTFLoader().loadAsync(`${import.meta.env.BASE_URL}${path.replace(/^\//, '')}`)
  gltf.scene.updateMatrixWorld(true)
  const box = new THREE.Box3().setFromObject(gltf.scene)
  const size = box.getSize(new THREE.Vector3())
  const center = box.getCenter(new THREE.Vector3())
  if (box.isEmpty() || Math.min(size.x, size.y, size.z) <= 0) throw new Error(`Empty model bounds: ${path}`)
  // Unit bounds let every instance use the dataset's real XY footprint and shared height.
  const normalize = new THREE.Matrix4().makeScale(1 / size.x, 1 / size.y, 1 / size.z)
    .multiply(new THREE.Matrix4().makeTranslation(-center.x, -box.min.y, -center.z))
  const parts: Part[] = []
  gltf.scene.traverse((node) => {
    if (!(node instanceof THREE.Mesh)) return
    const geometry = node.geometry.clone().applyMatrix4(node.matrixWorld).applyMatrix4(normalize)
    parts.push({ geometry, material: node.material })
    node.geometry.dispose()
  })
  return parts
}

/** One load per model in this layer, instanced per primitive, with explicit GPU cleanup. */
export function addObjectModels(parent: THREE.Object3D, plans: FloorPlan[], onReady: (count: number) => void) {
  let disposed = false
  const instances: THREE.InstancedMesh[] = []
  const templates: Part[][] = []
  const groups = new Map<string, PlacedAsset[]>()
  for (const plan of plans) {
    for (const asset of plan.assets) {
      if (asset.floor_id !== plan.floor.id || !asset.position.every(Number.isFinite)) continue
      const path = objectVisual(asset).model_path
      const group = groups.get(path) ?? []
      group.push({ asset, elevation: plan.floor.elevation_m })
      groups.set(path, group)
    }
  }
  void Promise.all([...groups].map(async ([path, assets]) => {
    let parts: Part[]
    try {
      parts = await loadParts(path)
    } catch (error) {
      console.warn(`Could not load object model ${path}; showing grey blocks.`, error)
      const geometry = new THREE.BoxGeometry(1, 1, 1).translate(0, 0.5, 0)
      parts = [{ geometry, material: new THREE.MeshStandardMaterial({ color: 0x9a9a9a, roughness: 1 }) }]
    }
    if (disposed) { disposeParts(parts); return }
    templates.push(parts)
    for (const part of parts) {
      const mesh = new THREE.InstancedMesh(part.geometry, part.material, assets.length)
      const matrix = new THREE.Matrix4()
      for (const [index, { asset, elevation }] of assets.entries()) {
        const { width_m, depth_m, rotation_deg } = asset.footprint
        const dimension = (value: number) => Number.isFinite(value) && value > 0 ? value : 0.5
        matrix.compose(
          new THREE.Vector3(asset.position[0], elevation, -asset.position[1]),
          new THREE.Quaternion().setFromAxisAngle(new THREE.Vector3(0, 1, 0), THREE.MathUtils.degToRad(Number.isFinite(rotation_deg) ? rotation_deg : 0)),
          new THREE.Vector3(dimension(width_m), objectVisual(asset).height_m, dimension(depth_m)),
        )
        mesh.setMatrixAt(index, matrix)
      }
      mesh.instanceMatrix.needsUpdate = true
      mesh.computeBoundingSphere()
      parent.add(mesh)
      instances.push(mesh)
    }
  })).then(() => { if (!disposed) onReady([...groups.values()].reduce((sum, assets) => sum + assets.length, 0)) })

  return () => {
    disposed = true
    for (const instance of instances) { parent.remove(instance); instance.dispose() }
    for (const parts of templates) disposeParts(parts)
  }
}
