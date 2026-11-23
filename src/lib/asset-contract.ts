// The 3D asset contract (spec section 9.6): what a GLB must hold before the site uses it.
// `asset-validate.ts` enforces these values, and `docs/standards/3d-assets.md` explains them.
// "MB" below means 1,000,000 bytes.
export const ASSET_KINDS = ['base-car', 'interior', 'product'] as const

export type AssetKind = (typeof ASSET_KINDS)[number]

export interface AssetContract {
  kind: AssetKind
  // Node names that must exist anywhere in the scene.
  requiredNodes: readonly string[]
  // Empty nodes (no mesh) that must exist anywhere in the scene.
  requiredAnchors: readonly string[]
  // Material names that at least one mesh in the scene must use.
  requiredMaterials: readonly string[]
  triangles: { min: number; max: number }
  maxBytes: number
  // The longest side of any texture, in pixels.
  maxTextureSize: number
  // Textures that only these materials use may go up to `maxSize` instead.
  detailTexture?: { materials: readonly string[]; maxSize: number }
}

export const CONTRACTS: Record<AssetKind, AssetContract> = {
  'base-car': {
    kind: 'base-car',
    requiredNodes: ['body'],
    requiredAnchors: [
      'wheel_FL',
      'wheel_FR',
      'wheel_RL',
      'wheel_RR',
      'mount_front_lip',
      'mount_trunk',
      'mount_wing',
      'mount_exhaust_L',
      'mount_exhaust_R',
      'mount_interior',
    ],
    requiredMaterials: ['paint', 'glass', 'trim', 'lights_front', 'lights_rear'],
    triangles: { min: 100_000, max: 200_000 },
    maxBytes: 8_000_000,
    maxTextureSize: 2048,
    detailTexture: { materials: ['paint'], maxSize: 4096 },
  },
  interior: {
    kind: 'interior',
    requiredNodes: [
      'interior',
      'cabin_shell',
      'dash',
      'console',
      'door_L',
      'door_R',
      'seat_driver',
      'seat_passenger',
      'steering_wheel',
    ],
    requiredAnchors: ['mount_seat_L', 'mount_seat_R', 'mount_steering', 'camera_driver_eye'],
    requiredMaterials: [],
    triangles: { min: 0, max: 150_000 },
    maxBytes: 6_000_000,
    maxTextureSize: 4096,
  },
  product: {
    kind: 'product',
    requiredNodes: [],
    requiredAnchors: [],
    requiredMaterials: [],
    triangles: { min: 0, max: 30_000 },
    maxBytes: 1_000_000,
    maxTextureSize: 2048,
  },
}

// How the geometry checks measure. Lengths are meters.
export const MEASUREMENTS = {
  // A base car's world bounding box: nose to tail along Z, ground to roof along Y.
  carLength: { min: 3.0, max: 6.0 },
  carHeight: { min: 0.9, max: 2.0 },
  // An interior's or a product's largest dimension.
  otherSize: { min: 0.05, max: 4.0 },
  // The mean Z of the wheel anchors may be this fraction of the wheelbase from the origin.
  originWheelbaseFraction: 0.02,
  // The lowest point of a base car may be this far from y = 0.
  groundTolerance: 0.03,
} as const
