# Third-party notices

Application code and Rust FNV implementation are original, licensed MIT.
The PNDB encoder/decoder independently implements the published byte layout; no porter-lib source or GPL library is linked into this program.

- Python runtime: PSF license; bundled by PyInstaller.
- Avalonia UI / Avalonia Fluent theme: MIT; version and package metadata are retained in `licenses/dotnet` and `licenses/dotnet-packages.lock.json`. Source: https://github.com/AvaloniaUI/Avalonia .
- Fluid.Avalonia.Acrylic 1.4.0: MIT; Copyright (c) 2025 KaranocaVe (original LiquidGlassAvaloniaUI work) and Copyright (c) 2026 Alpaq92 (renamed fork and modifications). The package's complete LICENSE is retained in `licenses/dotnet/Fluid.Avalonia.Acrylic/LICENSE`. Source: https://github.com/Alpaq92/Fluid.Avalonia.Acrylic/tree/013590eaa93666d368d775efdb3d7715591a4232 ; original project: https://github.com/KaranocaVe/LiquidGlassAvaloniaUI . The glass effect samples the application's own background through the Skia renderer.
- .NET NativeAOT runtime: MIT; source https://github.com/dotnet/runtime . The interface is compiled to a native Windows executable and does not require a separately installed .NET runtime.
- SkiaSharp / native Skia and HarfBuzz: package license metadata and component notices are retained in the release license directory; see the corresponding NuGet package entries.
- PySide6 / Qt are used only by the legacy reference GUI and tests in the source tree. They are not included in the 2.0 installer or its Python worker.
- NumPy: BSD-3-Clause, plus component notices included in its distribution.
- PyOpenCL: MIT; https://github.com/inducer/pyopencl . GPU drivers are provided by the user, not bundled.
- pytools, siphash24, platformdirs, typing_extensions: licenses copied from installed distribution metadata in the release.
- python-lz4: BSD-3-Clause; underlying LZ4 BSD-2-Clause.
- Rust lz4_flex: MIT, with dependencies listed in native/Cargo.lock.
- Rust serde_json and dependencies: MIT / Apache-2.0 where declared, notices collected during packaging.
- PyInstaller: GPL-2.0-or-later with bootloader exception; application distribution uses that exception.

The cod-name-db data and Saluki/game files are not included. Importing local data does not grant redistribution rights. Saluki merged indexes prepared locally are separate user artifacts.

Version inventory and package licenses are generated into the release `licenses` directory. Build source, native source, lockfiles and scripts are supplied in a source archive for reproducibility.

Independent verification uses ate47/atian-cod-tools hash_mini.hpp under its MIT license; full copyright and license are retained in tests/reference/hash_mini.hpp in the source archive. The production hash implementations are separately written. Algorithm provenance is documented in docs/hash-algorithm-coverage.md.

The community-table regression fixture contains original synthetic names and independently calculated reference hashes. Its table filenames exercise import routing; it does not redistribute rows from cod-name-db.
