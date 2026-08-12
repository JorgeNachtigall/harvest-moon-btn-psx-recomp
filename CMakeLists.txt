cmake_minimum_required(VERSION 3.20)
project(HarvestMoonBTNRecomp C CXX)

set(CMAKE_C_STANDARD 99)
set(CMAKE_CXX_STANDARD 17)

# The framework is a git submodule at ./psxrecomp, pinned to an exact commit.
set(PSXRECOMP_ROOT "${CMAKE_CURRENT_SOURCE_DIR}/psxrecomp")

set(PSX_RECOMP_UI OFF CACHE BOOL "" FORCE)

# Only the OpenBIOS backend is generated for this project. The framework's
# default stem list also expects SCPH1001, which fails configure without a
# retail BIOS dump.
set(PSXRECOMP_BIOS_STEMS "OpenBIOS" CACHE STRING "" FORCE)

include("${PSXRECOMP_ROOT}/runtime/runtime.cmake")

# Emitted by tools/regen.sh: N sharded translation units plus one dispatch table.
file(GLOB GAME_FULL CONFIGURE_DEPENDS
  "${CMAKE_CURRENT_SOURCE_DIR}/generated/*_full.c"
  "${CMAKE_CURRENT_SOURCE_DIR}/generated/*_full_*.c")
file(GLOB GAME_DISPATCH
  "${CMAKE_CURRENT_SOURCE_DIR}/generated/*_dispatch.c")

if(NOT GAME_FULL)
  message(FATAL_ERROR
    "No generated game C found in ${CMAKE_CURRENT_SOURCE_DIR}/generated.\n"
    "Run tools/regen.sh first — the recompiled C is build output and is not "
    "tracked in this repository.")
endif()

# Overlays baked into the executable, if tools/bake_overlays.sh has produced
# them. This is optional: without it the runtime still loads overlay shards
# from cache/ at launch, which is the same code by a different route. Baked in
# is what tools/make_app.sh wants — a single self-contained binary with no
# cache directory to carry alongside it.
set(GAME_OVERLAY_STATIC "${CMAKE_CURRENT_SOURCE_DIR}/generated/overlays_static.c")
if(EXISTS "${GAME_OVERLAY_STATIC}")
  message(STATUS "overlays: baking ${GAME_OVERLAY_STATIC} into the executable")
else()
  message(STATUS "overlays: none baked — the runtime will load shards from cache/ "
                 "(run tools/bake_overlays.sh to bake them in)")
  set(GAME_OVERLAY_STATIC "")
endif()

psxrecomp_add_runtime_target(psx-runtime
  GAME_GENERATED_FULL_C     "${GAME_FULL}"
  GAME_GENERATED_DISPATCH_C "${GAME_DISPATCH}"
  GAME_OVERLAY_STATIC_C     "${GAME_OVERLAY_STATIC}"
  WINDOW_TITLE              "Harvest Moon: Back to Nature (Recompiled)"
  DEFAULT_GAME_CONFIG_PATH  "game.toml"
)
