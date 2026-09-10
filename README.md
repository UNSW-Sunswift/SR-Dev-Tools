# Sunswift Dev Tools

Developer tooling for SR-Mjolnir and SR-Gungnir, SR8's high level repositories. Also now includes tooling for SR-Amsvartnir, SR8's firmware repository
Includes:

- `srpkg`: creates a new DDS package in your current working directory
- `srbuild`: wraps CMake to configure, build, and install targets
- `srlow`: wraps CMake and Ceedling to build and test firmware modules

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

## `srpkg`

Creates a new DDS package in the **current working directory**. Same idea as `ros2 pkg create`.

```bash
srpkg create <package_name>
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

Package names must be `snake_case`. `srpkg` only checks for a duplicate name in the current directory and does not search the rest of your repository. If you have a build system which builds multiple executables from different directories, it is on you to make sure no packages (and so executables) share a name.

## `srbuild`

Invokes CMake to configure, build, and install targets. Assumes top level CMakeLists is at your current working directory, or discovers the repository root (see below).

### Repository root discovery

`srbuild` looks for a `.sunswift-evsn` marker file, walking up from your current directory. The nearest directory containing it is treated as the root, and is assumed to contain your top-level `CMakeLists.txt`.

### Building

```bash
# Build and install everything
srbuild all

# Build and install specific targets
srbuild target node1 node2 ...

# Delete the entire build/ directory
srbuild clean
```

### Platform / toolchain selection

```bash
srbuild all --linux                              # native build, no toolchain file
srbuild all --qnx=cmake/qnx_toolchain.cmake       # cross-compile using the given toolchain file
```

You must supply `--qnx` or `--linux` are mutually exclusive. `--qnx` takes a path to a CMake toolchain file, resolved **relative to your current working directory** (not the discovered repo root).

### Output layout

Given a discovered root, `srbuild` produces:

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

### Parallel jobs

```bash
srbuild all --jobs 4
srbuild target node1 -j 16
```

Defaults to 8 parallel jobs.

## `srlow`

Wraps CMake and Ceedling to build and test the STM32 firmware modules in SR-Amsvartnir.

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

## Example workflow
SR-Gungnir and SR-Mjolnir:
```bash
cd path/to/your/project/src
srpkg create my_dds_node
# fill in my_dds_node/src, include/, and CMakeLists.txt

cd path/to/your/project
srbuild target my_dds_node
# or
srbuild all
```
SR-Amsvartnir:
```bash
# create STM32 Cube MX project in src/
# add the install section to CMakeLists.txt
srlow build all --preset Debug
# or
srlow build target my_project --preset Debug
# Create src/my_project/Test and initialise as a Ceedling project
srlow test target my_project
```
## Contributors
- Ryan Wong || z5417983
- Henry Jiang || z5416365
