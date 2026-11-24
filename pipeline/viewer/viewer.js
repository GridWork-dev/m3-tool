// The throwaway viewer for the Phase 0.6 3D spike. Plain ES module, no build step: three comes
// from the import map in index.html. Query: ?car=<work path>&interior=<work path>&wheel=<work path>,
// plus optional gen=<id> (default e46), eye=x,y,z in meters, backend=webgl.
//
// The asset contract (docs/standards/3d-assets.md) is what makes this work: meters, Y up, nose
// toward -Z, origin under the middle of the wheelbase. Materials `paint` and `glass` are driven
// by name, wheels go on the `wheel_*` anchors, and the interior (authored in the car frame) goes
// on the car origin.
import * as THREE from 'three'
import { OrbitControls } from 'three/addons/controls/OrbitControls.js'
import { RoomEnvironment } from 'three/addons/environments/RoomEnvironment.js'
import { MeshoptDecoder } from 'three/addons/libs/meshopt_decoder.module.js'
import { GLTFLoader } from 'three/addons/loaders/GLTFLoader.js'

const WHEEL_ANCHORS = ['wheel_FL', 'wheel_FR', 'wheel_RL', 'wheel_RR']
// Left wheels are authored for the right side, so they turn half a revolution about Y.
const isLeft = (anchorName) => anchorName.endsWith('L')
// The glass is a parameter of the `glass` material, so the viewer sets its tint opacity itself.
const GLASS_DEFAULT_OPACITY = 0.35
const ORBIT_POSITION = [5.4, 2.8, -6.6]
const ORBIT_TARGET = [0, 0.65, 0]
const ORBIT_FOV = 32
const DRIVER_FOV = 75
const PITCH_LIMIT = THREE.MathUtils.degToRad(85)

const $ = (id) => {
  const element = document.getElementById(id)
  if (!element) throw new Error(`index.html has no #${id}`)
  return element
}

const params = new URLSearchParams(location.search)

// A path under the work dir, as the server's /work/ route wants it.
function workUrl(path) {
  const parts = path.split('/').filter((part) => part !== '')
  if (parts.some((part) => part === '..')) throw new Error(`path ${path} leaves the work dir`)
  return `/work/${parts.map(encodeURIComponent).join('/')}`
}

function parseEye(text) {
  const values = text.split(',').map((part) => Number(part.trim()))
  if (values.length !== 3 || values.some((value) => !Number.isFinite(value))) {
    throw new Error(`?eye= takes x,y,z in meters, got "${text}"`)
  }
  return values
}

async function loadEye(gen) {
  const override = params.get('eye')
  if (override !== null) return { eye: parseEye(override), source: '?eye= override' }
  const response = await fetch(`/api/eye?gen=${encodeURIComponent(gen)}`)
  if (!response.ok) throw new Error(`/api/eye?gen=${gen} answered ${response.status}`)
  const { x, y, z } = await response.json()
  return { eye: [x, y, z], source: `data/generations/${gen}.yaml` }
}

function materialsNamed(root, name) {
  const found = new Set()
  root.traverse((object) => {
    if (!object.isMesh) return
    for (const material of [object.material].flat()) {
      if (material.name === name) found.add(material)
    }
  })
  return [...found]
}

function requireNamed(root, name, what) {
  const object = root.getObjectByName(name)
  if (!object) throw new Error(`${what} has no node named "${name}"`)
  return object
}

const fixed = (values, digits = 3) => values.map((value) => value.toFixed(digits)).join(', ')

async function start() {
  const carPath = params.get('car')
  if (!carPath) throw new Error('add ?car=<path under the work dir> to the URL')
  const interiorPath = params.get('interior')
  const wheelPath = params.get('wheel')
  const gen = params.get('gen') ?? 'e46'

  const stage = $('stage')
  const renderer = new THREE.WebGPURenderer({
    antialias: true,
    forceWebGL: params.get('backend') === 'webgl',
  })
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
  // Neutral keeps a base color close to what the paint input says.
  renderer.toneMapping = THREE.NeutralToneMapping
  stage.append(renderer.domElement)
  await renderer.init()
  const backend = renderer.backend.isWebGPUBackend === true ? 'webgpu' : 'webgl2'

  const scene = new THREE.Scene()
  scene.background = new THREE.Color(0x4a5160)
  const pmrem = new THREE.PMREMGenerator(renderer)
  scene.environment = pmrem.fromScene(new RoomEnvironment(), 0.04).texture
  scene.environmentIntensity = 0.9
  const sun = new THREE.DirectionalLight(0xffffff, 1.4)
  sun.position.set(4, 8, -3)
  scene.add(sun)
  const ground = new THREE.Mesh(
    new THREE.PlaneGeometry(40, 40),
    new THREE.MeshStandardMaterial({ color: 0x2a2e36, roughness: 0.95, metalness: 0 }),
  )
  ground.rotation.x = -Math.PI / 2
  scene.add(ground)
  const grid = new THREE.GridHelper(20, 20, 0x59606d, 0x3a3f4a)
  grid.position.y = 0.002
  scene.add(grid)

  const loader = new GLTFLoader().setMeshoptDecoder(MeshoptDecoder)
  const loadGlb = async (path) => (await loader.loadAsync(workUrl(path))).scene
  const [carRoot, interiorScene, wheelRoot, eyeInfo] = await Promise.all([
    loadGlb(carPath),
    interiorPath ? loadGlb(interiorPath) : null,
    wheelPath ? loadGlb(wheelPath) : null,
    loadEye(gen),
  ])
  const eye = eyeInfo.eye
  scene.add(carRoot)

  const paintMaterials = materialsNamed(carRoot, 'paint')
  const glassMaterials = materialsNamed(carRoot, 'glass')
  if (paintMaterials.length === 0) throw new Error('the car has no material named "paint"')
  if (glassMaterials.length === 0) throw new Error('the car has no material named "glass"')
  for (const material of glassMaterials) {
    material.transparent = true
    material.depthWrite = false
    material.needsUpdate = true
  }

  // One holder per wheel anchor. The holder turns, so the wheel's own transform stays as authored.
  const wheelHolders = []
  if (wheelRoot) {
    for (const name of WHEEL_ANCHORS) {
      const anchor = requireNamed(carRoot, name, 'the car')
      const holder = new THREE.Group()
      holder.name = `wheel_holder_${name}`
      if (isLeft(name)) holder.rotation.y = Math.PI
      holder.add(wheelRoot.clone(true))
      anchor.add(holder)
      wheelHolders.push(holder)
    }
  }

  // The interior is authored in the car frame, so it goes on the car origin with no offset.
  let interiorRoot = null
  let interiorEyeAnchor = null
  if (interiorScene) {
    interiorRoot = requireNamed(interiorScene, 'interior', 'the interior')
    interiorEyeAnchor = interiorScene.getObjectByName('camera_driver_eye') ?? null
    scene.add(interiorScene)
  }
  scene.updateMatrixWorld(true)

  const orbitCamera = new THREE.PerspectiveCamera(ORBIT_FOV, 1, 0.05, 200)
  const driverCamera = new THREE.PerspectiveCamera(DRIVER_FOV, 1, 0.02, 200)
  driverCamera.rotation.order = 'YXZ'
  driverCamera.position.set(...eye)
  const controls = new OrbitControls(orbitCamera, renderer.domElement)
  controls.enableDamping = false
  controls.maxPolarAngle = Math.PI / 2 - 0.02
  const resetOrbit = () => {
    orbitCamera.position.set(...ORBIT_POSITION)
    controls.target.set(...ORBIT_TARGET)
    controls.update()
  }
  resetOrbit()

  let yaw = 0
  let pitch = 0
  const applyDriverLook = () => driverCamera.rotation.set(pitch, yaw, 0)
  applyDriverLook()

  // The values the controls hold. `apply` pushes them into the scene and the DOM, and `state`
  // reads the scene back, so a control that doesn't reach the scene shows up as a wrong state.
  const view = {
    camera: 'orbit',
    paint: `#${paintMaterials[0].color.getHexString()}`,
    glassVisible: true,
    glassOpacity: GLASS_DEFAULT_OPACITY,
    wheelsVisible: wheelHolders.length > 0,
    interiorVisible: interiorRoot !== null,
    fov: DRIVER_FOV,
  }
  const defaults = { ...view }

  const inputs = {
    orbit: $('camera-orbit'),
    driver: $('camera-driver'),
    paint: $('paint'),
    glassVisible: $('glass-visible'),
    glassOpacity: $('glass-opacity'),
    wheelsVisible: $('wheels-visible'),
    interiorVisible: $('interior-visible'),
    fov: $('fov'),
  }
  inputs.wheelsVisible.disabled = wheelHolders.length === 0
  inputs.interiorVisible.disabled = interiorRoot === null

  function apply() {
    for (const material of paintMaterials) material.color.set(view.paint)
    for (const material of glassMaterials) {
      material.visible = view.glassVisible
      material.opacity = view.glassOpacity
    }
    for (const holder of wheelHolders) holder.visible = view.wheelsVisible
    if (interiorRoot) interiorRoot.visible = view.interiorVisible
    driverCamera.fov = view.fov
    driverCamera.updateProjectionMatrix()
    controls.enabled = view.camera === 'orbit'

    inputs.orbit.checked = view.camera === 'orbit'
    inputs.driver.checked = view.camera === 'driver'
    inputs.paint.value = view.paint
    inputs.glassVisible.checked = view.glassVisible
    inputs.glassOpacity.value = String(view.glassOpacity)
    $('glass-opacity-value').textContent = view.glassOpacity.toFixed(2)
    inputs.wheelsVisible.checked = view.wheelsVisible
    inputs.interiorVisible.checked = view.interiorVisible
    inputs.fov.value = String(view.fov)
    $('fov-value').textContent = String(view.fov)
  }

  inputs.orbit.addEventListener('change', () => {
    if (inputs.orbit.checked) view.camera = 'orbit'
    apply()
  })
  inputs.driver.addEventListener('change', () => {
    if (inputs.driver.checked) view.camera = 'driver'
    apply()
  })
  inputs.paint.addEventListener('input', () => {
    view.paint = inputs.paint.value
    apply()
  })
  inputs.glassVisible.addEventListener('change', () => {
    view.glassVisible = inputs.glassVisible.checked
    apply()
  })
  inputs.glassOpacity.addEventListener('input', () => {
    view.glassOpacity = Number(inputs.glassOpacity.value)
    apply()
  })
  inputs.wheelsVisible.addEventListener('change', () => {
    view.wheelsVisible = inputs.wheelsVisible.checked
    apply()
  })
  inputs.interiorVisible.addEventListener('change', () => {
    view.interiorVisible = inputs.interiorVisible.checked
    apply()
  })
  inputs.fov.addEventListener('input', () => {
    view.fov = Number(inputs.fov.value)
    apply()
  })

  // Drag to look, driver camera only. The orbit camera has its own controls.
  let dragging = null
  const canvas = renderer.domElement
  canvas.addEventListener('pointerdown', (event) => {
    if (view.camera !== 'driver') return
    dragging = { x: event.clientX, y: event.clientY }
    canvas.setPointerCapture(event.pointerId)
  })
  canvas.addEventListener('pointermove', (event) => {
    if (!dragging) return
    // Scale by the field of view, so a drag turns the view by about the same fraction of the screen.
    const perPixel = THREE.MathUtils.degToRad(view.fov) / canvas.clientHeight
    yaw -= (event.clientX - dragging.x) * perPixel
    pitch = THREE.MathUtils.clamp(
      pitch - (event.clientY - dragging.y) * perPixel,
      -PITCH_LIMIT,
      PITCH_LIMIT,
    )
    dragging = { x: event.clientX, y: event.clientY }
    applyDriverLook()
  })
  const endDrag = () => {
    dragging = null
  }
  canvas.addEventListener('pointerup', endDrag)
  canvas.addEventListener('pointercancel', endDrag)

  const resize = () => {
    const width = Math.max(1, stage.clientWidth)
    const height = Math.max(1, stage.clientHeight)
    renderer.setSize(width, height, false)
    for (const camera of [orbitCamera, driverCamera]) {
      camera.aspect = width / height
      camera.updateProjectionMatrix()
    }
  }
  new ResizeObserver(resize).observe(stage)
  resize()

  const readout = $('readout')
  const lines = [`eye (m): ${fixed(eye)}`, `  from ${eyeInfo.source}`]
  if (interiorEyeAnchor) {
    const anchor = interiorEyeAnchor.getWorldPosition(new THREE.Vector3())
    const deltaMm = [anchor.x - eye[0], anchor.y - eye[1], anchor.z - eye[2]].map((v) => v * 1000)
    lines.push(`interior camera_driver_eye (m): ${fixed(anchor.toArray())}`)
    lines.push(`  minus eye (mm): ${fixed(deltaMm, 0)}`)
  }
  readout.textContent = lines.join('\n')

  const reset = () => {
    Object.assign(view, defaults)
    yaw = 0
    pitch = 0
    applyDriverLook()
    resetOrbit()
    apply()
  }
  $('reset').addEventListener('click', reset)

  let frames = 0
  renderer.setAnimationLoop(() => {
    renderer.render(scene, view.camera === 'orbit' ? orbitCamera : driverCamera)
    frames += 1
  })
  apply()

  // Resolves once `count` more frames have been drawn, so a screenshot sees the latest change.
  const settle = (count = 4) =>
    new Promise((resolve) => {
      const target = frames + count
      const tick = () => (frames >= target ? resolve() : requestAnimationFrame(tick))
      tick()
    })

  const status = $('status')
  status.className = 'muted'
  status.textContent = `renderer: ${backend}\ncar: ${carPath}${interiorPath ? `\ninterior: ${interiorPath}` : ''}${wheelPath ? `\nwheel: ${wheelPath}` : ''}`

  const position = (object) => {
    // `+ 0` turns -0 into 0.
    const at = object.getWorldPosition(new THREE.Vector3())
    return [at.x + 0, at.y + 0, at.z + 0]
  }
  return {
    // What the controls hold, read back from the scene. Keys and order are the page's contract.
    state: () => {
      scene.updateMatrixWorld(true)
      return {
        camera: view.camera,
        paint: `#${paintMaterials[0].color.getHexString()}`,
        glassVisible: glassMaterials.every((material) => material.visible),
        glassOpacity: glassMaterials[0].opacity,
        wheelsVisible: wheelHolders.length > 0 && wheelHolders.every((holder) => holder.visible),
        interiorVisible: interiorRoot ? interiorRoot.visible : false,
        interiorPosition: interiorRoot ? position(interiorRoot) : [0, 0, 0],
        eye: [...eye],
        backend,
      }
    },
    // Every default back: paint, glass, wheels, interior, the orbit camera and its pose.
    reset,
    settle,
  }
}

// `state`, `reset` and `settle` appear on `__viewer` before `ready` resolves, and `ready` rejects
// when the page can't start, so a script can await it and fail loudly.
const viewer = {}
viewer.ready = start().then((api) => {
  Object.assign(viewer, api)
})
viewer.ready.catch((error) => {
  const status = $('status')
  status.className = 'error'
  status.textContent = error instanceof Error ? error.message : String(error)
  console.error(error)
})
window.__viewer = viewer
