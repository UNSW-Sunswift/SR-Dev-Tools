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

Helper for building, testing, statically analysing and creating DDS packages in SR-Mjolnir and SR-Gungnir. Replaces the old `srbuild`, `srpkg`, `sranalyse` and `srtest` tools.

```bash
srhigh build ...     # was srbuild
srhigh test ...      # was srtest (S130_dev-tools)
srhigh analyse ...   # was sranalyse
srhigh pkg ...       # was srpkg
```

### Repository root discovery

`srhigh build`, `srhigh test` and `srhigh analyse` look for a `.sunswift-evsn` marker file, walking up from your current directory. The nearest directory containing it is treated as the root, and is assumed to contain your top-level `CMakeLists.txt`. `srhigh pkg` does not need the marker.

### Building

Invokes CMake to configure, build, and install targets.

```bash
# Build and install everything
srhigh build all --linux

# Build and install specific targets
srhigh build target node1 node2 ... --linux

# Delete the entire build/ directory
srhigh build clean
```

#### Platform / toolchain selection

```bash
srhigh build all --linux                              # native build, no toolchain file
srhigh build all --qnx=cmake/qnx_toolchain.cmake       # cross-compile using the given toolchain file
```

You must supply one of `--qnx` or `--linux` for `all` and `target`; they are mutually exclusive. `--qnx` takes a path to a CMake toolchain file, resolved **relative to your current working directory** (not the discovered repo root).

#### Output layout

Given a discovered root, `srhigh build` produces:

```
<root>/
├── CMakeLists.txt
├── build/
│   └── linux/   (or qnx/, depending on the flag used)
├── deploy/
│   └── linux/   (or qnx/)
│       ├── bin/
│       └── param/
```

`build/` holds CMake's intermediate files (don't touch it directly). `deploy/` holds the stuff to deploy (duh)

#### Parallel jobs

```bash
srhigh build all --linux --jobs 4
srhigh build target node1 --linux -j 16
```

Defaults to 8 parallel jobs.

### Testing

Discovers and runs GoogleTest binaries, then prints a summary of pass/fail and line and function coverage (via `gcov`) for each.

```bash
# Run every test binary
srhigh test all

# Run everything except specific nodes
srhigh test all --except tpms motor

# Run only the nodes you are working on
srhigh test target pedal_box

# Run only test cases matching a GoogleTest filter
srhigh test target pedal_box -f "*Parse*"

# Export gtest XML reports and a summary.json to a directory (relative to your CWD)
srhigh test all -o build/test-results

# Monitor AddressSanitizer (leak detection on) and dump its stack trace on failure
srhigh test target pedal_box --asan
```

Build with `srhigh build all --linux` first. Tests are always run from `build/linux/`, since QNX binaries can't run on the host.

A test binary is any executable named `test_<node>` (no file extension) anywhere under `build/linux/`. Each binary has a 30 second timeout. With `--asan`/`-a`, binaries are run with `ASAN_OPTIONS=detect_leaks=1` (the node must be compiled with `-fsanitize=address`). Coverage is reported only if the node is compiled with `--coverage`, and is read from the `<node>_logic` (or `<node>`) CMake target's object directory. Passing nodes under 60% line coverage are flagged.

### Analysing

```bash
srhigh analyse --linux   # analyse build/linux
srhigh analyse --qnx     # analyse build/qnx
```

Runs Scitools Understand `codecheck` (MISRA C++ 2023) over the repo. Requires `und` to be installed and licensed, a `misra-cpp2023.json` config file at the repo root, and a `compile_commands.json` in the chosen build directory (run `srhigh build` first).

Files to check are listed in an `analyse.txt` at the repo root, with paths relative to the root. Comments and glob patterns are supported, the same as `srlow analyse`. Results are written to `analysis/` at the repo root.

### Creating packages

Creates a new DDS package in the **current working directory**. Same idea as `ros2 pkg create`.

```bash
srhigh pkg create <package_name>
```

This creates:

```
<package_name>/
├── .srpkg                             # Package metadata marker
├── src/
│   └── main.cpp
├── include/
├── test/
├── param/
│   └── <package_name>_param.toml
├── CMakeLists.txt                     # Build configuration template
└── README.md
```

Package names must be `snake_case`. `srhigh pkg` only checks for a duplicate name in the current directory and does not search the rest of your repository. If you have a build system which builds multiple executables from different directories, it is on you to make sure no packages (and so executables) share a name.

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
# Add a test_my_dds_node GoogleTest executable, then run:
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
