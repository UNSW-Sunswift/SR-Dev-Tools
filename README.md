# Sunswift Dev Tools

Developer tooling for SR-Mjolnir and SR-Gungnir, SR8's high level repositories. Also now includes tooling for SR-Amsvartnir, SR8's firmware repository.
Includes:

- `srhigh`: helper for CMake building, GoogleTest unit testing, Understand static analysis and DDS package creation
- `srlow`: helper for building, ceedling unit testing and Understand static analysis
- `srdbcc`: generates C source and header files from a DBC database

Tools are installed as a [uv](https://docs.astral.sh/uv/) tool.

`srlaunch` (process launcher) has moved to [`deprecated/`](deprecated/). QNX targets should use QNX's own process management. It is being replaced by a cross-platform orchestrator (Seb's thesis).

## Installation

Install globally as a uv tool (recommended):

```bash
uv tool install git+https://github.com/UNSW-Sunswift/SR-Dev-Tools.git
```

This puts all CLI tools on your PATH. To upgrade later:

```bash
uv tool upgrade sr-dev-tools
```

For local development on this repo itself:

```bash
git clone git@github.com:UNSW-Sunswift/SR-Dev-Tools.git
cd SR-Dev-Tools
uv tool install --editable .
```

From a Dockerfile:

```dockerfile
RUN uv tool install git+https://github.com/UNSW-Sunswift/SR-Dev-Tools.git
```

## `srhigh`

Build, test, analyse and create DDS packages in SR-Mjolnir and SR-Gungnir.

`build`, `test` and `analyse` find the repo root by walking up from your current directory to the nearest `.sunswift-evsn` marker. The root must contain your top-level `CMakeLists.txt`. `pkg` works in any directory.

### Build

```bash
srhigh build all --linux                     # build and install everything
srhigh build target node1 node2 --linux      # build and install specific targets
srhigh build all --qnx=cmake/qnx.cmake       # cross-compile with a toolchain file (relative to your CWD)
srhigh build all --linux -j 16               # parallel jobs (default 8)
srhigh build all --linux --coverage --asan   # test build with coverage and AddressSanitizer
srhigh build clean                           # delete build/
```

`--linux` or `--qnx=<toolchain>` is required for `all` and `target`. CMake files go to `build/<platform>/`, and installed binaries and params go to `deploy/<platform>/{bin,param}/`.

`--coverage` and `--asan` are for testing only, and Linux only. Without them you get a normal build, and you can switch between the two without a clean. They work in projects whose CMake reads `SR_ENABLE_COVERAGE` and `SR_ENABLE_ASAN`, such as SR-Gungnir's `cmake/SRTesting.cmake`.

### Test

```bash
srhigh test all                              # run every test binary
srhigh test all --except tpms motor          # skip some nodes
srhigh test target pedal_box                 # run specific nodes
srhigh test target pedal_box -f "*Parse*"    # GoogleTest filter
srhigh test all -o build/test-results        # write gtest XML + summary.json
```

Runs every `test_<node>` executable in `build/linux/` and prints pass/fail for each, with a 30 s timeout per binary. Build with `srhigh build all --linux` first.

- With a `--coverage` build, results also show line and function coverage, and nodes under 60% line coverage are flagged.
- With an `--asan` build, a test with a memory bug (buffer overflow, use-after-free, double free, leak) fails, and its AddressSanitizer report shows where it happened. The test log says whether AddressSanitizer is on.

### Analyse

```bash
srhigh analyse --linux                       # analyse build/linux
srhigh analyse --qnx                         # analyse build/qnx
```

Runs Understand `codecheck` (MISRA C++ 2023) on the files listed in `analyse.txt` at the repo root. Globs and `#` comments are allowed. It needs a licensed `und`, `misra-cpp2023.json` at the repo root, and `compile_commands.json` from `srhigh build`. Results go to `analysis/`.

### Pkg

```bash
srhigh pkg create <package_name>
```

Creates a `snake_case` DDS package in your current directory:

```
<package_name>/
├── .srpkg
├── CMakeLists.txt
├── README.md
├── include/
│   ├── <package_name>.hpp
│   └── <package_name>_logic.hpp
├── param/
│   └── <package_name>_param.toml
├── src/
│   ├── main.cpp                    # creates and spins the node
│   ├── <package_name>.cpp          # the SRNode class
│   └── <package_name>_logic.cpp    # testable logic, no DDS
└── test/
    └── unit/
        └── test_<package_name>.cpp
```

It's ready for unit tests: put DDS-free logic in `<package_name>_logic`, and GoogleTest tests in `test/unit/`. `CMakeLists.txt` builds `test_<package_name>` whenever the project provides GoogleTest, so no CMake edits are needed.

It only checks for a duplicate name in the current directory, so make sure package names are unique across the repo.

## `srlow`

Helper for CMake, Ceedling and Understand to build, test and analyse the STM32 firmware modules in SR-Amsvartnir.

### Repository root discovery

`srlow` looks for a `.sunswift-firmware` marker file, walking up from your current directory. The nearest directory containing it is the root, and must contain a `src/` directory holding one subdirectory per STM32 module.

Each module directory must have its own `CMakeLists.txt` and `CMakePresets.json` at its top level. A module may also contain a `Test/` directory, which must be a Ceedling project.

### Building

```bash
# Build and install every module
srlow build all --preset [Debug | Release]

# Build and install specific modules (directory names)
srlow build target module1 module2 --preset debug

# Delete every module's build/ directory
srlow build clean
```

`--preset` / `-p` is required for `all` and `target`, and names a CMake preset defined in each module's `CMakePresets.json`.

### Testing

```bash
# Test every module
srlow test all

# Test specific modules
srlow test target module1 module2
```

Runs `ceedling test:all gcov:all valgrind:all` in each module's `Test/` directory.

### Analysing

```bash
# Analyse every module
srlow analyse all --preset [Debug | Release]

# Analyse specific modules
srlow analyse target module1 module2 --preset debug
```

Runs Scitools Understand `codecheck` (MISRA-C 2025) on each module. Requires `und` to be installed and licensed, a `misra-c2025.json` config file at the repo root, and a `compile_commands.json`. This can easily be gotten by running srlow build.

A module is analysed only if it has an `analyse.txt` file at its top level, listing which files to check. All paths are relative to module root:

```
# This is a comment
Core/Src/my_math.c
Core/Src/*.c          # inline comments and glob patterns are both supported
Drivers/**/*.c
```

### Installing

All `srlow build...` commands also installs generated binaries into a repo root `deploy/module_name/` directory. In each STM32 projects' CMakeLists.txt, the following addition is required:

```bash
# Installing ===========================
# Auto-generate binary from ELF
add_custom_command(
    TARGET ${CMAKE_PROJECT_NAME}
    POST_BUILD 
    COMMAND ${CMAKE_OBJCOPY} -O binary $<TARGET_FILE:${CMAKE_PROJECT_NAME}> $<TARGET_FILE_DIR:${CMAKE_PROJECT_NAME}>/${CMAKE_PROJECT_NAME}.bin
)

install(
    FILES
    $<TARGET_FILE_DIR:${CMAKE_PROJECT_NAME}>/${CMAKE_PROJECT_NAME}.bin
    $<TARGET_FILE:${CMAKE_PROJECT_NAME}>
    DESTINATION ${CMAKE_PROJECT_NAME}
)
```

## `srdbcc`

Generates C source and header files from a DBC database using `cantools`.

```bash
srdbcc path/to/database.dbc

srdbcc path/to/database.dbc --database-name can --output-directory generated
```

The output directory is created if it does not exist. The generated files are
named `<database-name>.h` and `<database-name>.c`; when `--database-name` is
omitted, the input filename stem is converted to snake case.

## Example workflow
SR-Gungnir and SR-Mjolnir:
```bash
cd path/to/your/project/src
srhigh pkg create my_dds_node
# fill in my_dds_node/src, include/, and CMakeLists.txt

cd path/to/your/project
srhigh build target my_dds_node --linux
# or
srhigh build all --linux
# add a test_my_dds_node GoogleTest executable, then:
srhigh build target my_dds_node test_my_dds_node --linux
srhigh test target my_dds_node
```
SR-Amsvartnir:
```bash
# create STM32 Cube MX project in src/
# add the install section to CMakeLists.txt
srlow build target my_project --preset Debug
# Create src/my_project/Test and initialise as a Ceedling project
srlow test target my_project
# Create analyse.txt file with target files, then run:
srlow analyse target my_project
```
## Contributors
- Ryan Wong || z5417983
- Henry Jiang || z5416365
- (srdbcc) Ryan Kwok || z5590821
- (srhigh test) Vipul Chiluvery
