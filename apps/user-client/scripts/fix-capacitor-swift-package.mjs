import { readFileSync, writeFileSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const packageFile = fileURLToPath(new URL('../src-capacitor/ios/App/CapApp-SPM/Package.swift', import.meta.url))
const source = `// swift-tools-version: 5.9
import PackageDescription

// Kept deterministic by scripts/fix-capacitor-swift-package.mjs after cap sync.
// Stable package junctions avoid machine-specific pnpm store paths.
let package = Package(
    name: "CapApp-SPM",
    platforms: [.iOS(.v15)],
    products: [
        .library(name: "CapApp-SPM", targets: ["CapApp-SPM"])
    ],
    dependencies: [
        .package(url: "https://github.com/ionic-team/capacitor-swift-pm.git", exact: "8.5.0"),
        .package(name: "CapacitorApp", path: "../../../node_modules/@capacitor/app"),
        .package(name: "CapacitorBrowser", path: "../../../node_modules/@capacitor/browser")
    ],
    targets: [
        .target(
            name: "CapApp-SPM",
            dependencies: [
                .product(name: "Capacitor", package: "capacitor-swift-pm"),
                .product(name: "Cordova", package: "capacitor-swift-pm"),
                .product(name: "CapacitorApp", package: "CapacitorApp"),
                .product(name: "CapacitorBrowser", package: "CapacitorBrowser")
            ]
        )
    ]
)
`

writeFileSync(packageFile, source, 'utf8')
const written = readFileSync(packageFile, 'utf8')
if (written.includes('\\') || written.includes('node_modules/.pnpm')) {
  throw new Error('Capacitor Swift package contains a machine-specific or Windows-only path.')
}
