// The `gltf-validator` package ships no types. This declares the part of its API we call.
declare module 'gltf-validator' {
  export interface ValidationMessage {
    code: string
    message: string
    // 0 error, 1 warning, 2 info, 3 hint
    severity: number
    pointer?: string
  }

  export interface ValidationReport {
    issues: {
      numErrors: number
      numWarnings: number
      numInfos: number
      numHints: number
      messages: ValidationMessage[]
    }
  }

  export interface ValidationOptions {
    uri?: string
    format?: 'glb' | 'gltf'
    // 0 means no limit.
    maxIssues?: number
    writeTimestamp?: boolean
  }

  // Rejects when the bytes are neither glTF nor GLB.
  export function validateBytes(
    data: Uint8Array,
    options?: ValidationOptions,
  ): Promise<ValidationReport>
}
