// The modules a source file loads, found with TypeScript's own parser, so a comment, a string or the
// way a line is written can't hide one or fake one. Used by the tests that say a module "imports
// nothing" (the contract file, the link policy).
import ts from 'typescript'

const specifierText = (node: ts.Node | undefined): string => {
  if (node === undefined) return '<none>'
  if (ts.isStringLiteralLike(node)) return node.text
  return node.getText()
}

// The specifier of each static import, re-export with a `from`, `import x = require()`, dynamic
// `import()` and `require()` call, in source order. A specifier that isn't a literal is returned as
// its source text.
export function modulesReached(source: string): string[] {
  const file = ts.createSourceFile('module.ts', source, ts.ScriptTarget.Latest, true)
  const found: string[] = []
  const visit = (node: ts.Node): void => {
    if ((ts.isImportDeclaration(node) || ts.isExportDeclaration(node)) && node.moduleSpecifier) {
      found.push(specifierText(node.moduleSpecifier))
    } else if (
      ts.isImportEqualsDeclaration(node) &&
      ts.isExternalModuleReference(node.moduleReference)
    ) {
      found.push(specifierText(node.moduleReference.expression))
    } else if (
      ts.isCallExpression(node) &&
      (node.expression.kind === ts.SyntaxKind.ImportKeyword ||
        (ts.isIdentifier(node.expression) && node.expression.text === 'require'))
    ) {
      found.push(specifierText(node.arguments[0]))
    }
    ts.forEachChild(node, visit)
  }
  visit(file)
  return found
}
