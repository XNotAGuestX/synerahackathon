import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import type { FloorPlan, Route } from '../../domain/types'

type FloorStack3DProps = {
  plans: FloorPlan[]
  route: Route | null
}

export function FloorStack3D({ plans, route }: FloorStack3DProps) {
  const host = useRef<HTMLDivElement>(null)

  useEffect(() => {
    const element = host.current
    if (!element || plans.length === 0) return
    const width = Math.max(element.clientWidth, 320)
    const height = 280
    const scene = new THREE.Scene()
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setSize(width, height)
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    element.replaceChildren(renderer.domElement)

    const points = plans.flatMap((plan) => plan.spaces.flatMap((space) => space.polygon))
    const xs = points.map(([x]) => x)
    const ys = points.map(([, y]) => y)
    const minX = Math.min(...xs)
    const maxX = Math.max(...xs)
    const minY = Math.min(...ys)
    const maxY = Math.max(...ys)
    const elevations = plans.map((plan) => plan.floor.elevation_m)
    const centerX = (minX + maxX) / 2
    const centerY = (minY + maxY) / 2
    const span = Math.max(maxX - minX, maxY - minY, 1)

    const camera = new THREE.PerspectiveCamera(40, width / height, 0.1, span * 20)
    camera.position.set(centerX + span * 0.2, Math.max(...elevations) + span * 0.8, centerY + span * 1.1)
    camera.lookAt(centerX, 0, centerY)
    scene.add(new THREE.AmbientLight(0xffffff, 1))

    const elevationByFloor = new Map(plans.map((plan) => [plan.floor.id, plan.floor.elevation_m]))
    for (const plan of plans) {
      for (const space of plan.spaces) {
        if (space.polygon.length < 3) continue
        const shape = new THREE.Shape()
        space.polygon.forEach(([x, y], index) => {
          if (index === 0) shape.moveTo(x, y)
          else shape.lineTo(x, y)
        })
        const mesh = new THREE.Mesh(
          new THREE.ShapeGeometry(shape),
          new THREE.MeshBasicMaterial({ color: 0xc2f44b, transparent: true, opacity: 0.45, side: THREE.DoubleSide }),
        )
        mesh.rotation.x = -Math.PI / 2
        mesh.position.y = plan.floor.elevation_m
        scene.add(mesh)
      }
    }
    for (const leg of route?.legs ?? []) {
      const elevation = elevationByFloor.get(leg.floor_id) ?? 0
      const geometry = new THREE.BufferGeometry().setFromPoints(
        leg.points.map(([x, y]) => new THREE.Vector3(x, elevation + 0.4, y)),
      )
      scene.add(new THREE.Line(geometry, new THREE.LineBasicMaterial({ color: 0xff765b })))
    }
    renderer.render(scene, camera)
    return () => {
      renderer.dispose()
      element.replaceChildren()
    }
  }, [plans, route])

  return <div ref={host} className="floor-stack-3d" role="img" aria-label="Three.js floor stack" />
}
