# Explicit sources keep this build independent of generated CubeMX CMake files.
set(STM32CUBE_F4_PATH "" CACHE PATH "Root of an installed STM32Cube_FW_F4 package")
set(_hal_modules i2c i2c_ex rcc rcc_ex flash flash_ex flash_ramfunc gpio dma dma_ex
    pwr pwr_ex cortex hal exti spi tim tim_ex uart)
set(_hal_sources "")
foreach(_module IN LISTS _hal_modules)
    if(_module STREQUAL "hal")
        list(APPEND _hal_sources STM32F4xx_HAL_Driver/Src/stm32f4xx_hal.c)
    else()
        list(APPEND _hal_sources "STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_${_module}.c")
    endif()
endforeach()
set(_cube_required ${_hal_sources}
    STM32F4xx_HAL_Driver/Inc/stm32f4xx_hal.h
    STM32F4xx_HAL_Driver/Inc/Legacy/stm32_hal_legacy.h
    CMSIS/Device/ST/STM32F4xx/Include/stm32f411xe.h CMSIS/Include/core_cm4.h)
function(_cube_validate drivers_dir result)
    foreach(_required IN LISTS _cube_required)
        if(NOT EXISTS "${drivers_dir}/${_required}")
            set(${result} FALSE PARENT_SCOPE)
            return()
        endif()
    endforeach()
    set(${result} TRUE PARENT_SCOPE)
endfunction()
function(_cube_path_error path)
    message(FATAL_ERROR
        "STM32CubeF4 HAL/CMSIS package is missing or incomplete: '${path}'. "
        "Install STM32Cube MCU Package for STM32F4 using STM32CubeMX, then set "
        "-DSTM32CUBE_F4_PATH=<STM32Cube_FW_F4_Vx.y.z> or the STM32CUBE_F4_PATH "
        "environment variable. Required: Drivers/STM32F4xx_HAL_Driver sources, "
        "Drivers/CMSIS/Device/ST/STM32F4xx/Include/stm32f411xe.h and "
        "Drivers/CMSIS/Include/core_cm4.h. No files are copied into this repository.")
endfunction()
# Explicit invalid paths are errors, even when another SDK is available.
if(NOT "${STM32CUBE_F4_PATH}" STREQUAL "")
    file(TO_CMAKE_PATH "${STM32CUBE_F4_PATH}" _explicit_cube)
elseif(DEFINED ENV{STM32CUBE_F4_PATH} AND NOT "$ENV{STM32CUBE_F4_PATH}" STREQUAL "")
    file(TO_CMAKE_PATH "$ENV{STM32CUBE_F4_PATH}" _explicit_cube)
endif()
if(DEFINED _explicit_cube)
    _cube_validate("${_explicit_cube}/Drivers" _explicit_valid)
    if(NOT _explicit_valid)
        _cube_path_error("${_explicit_cube}")
    endif()
endif()
_cube_validate("${PROJECT_SOURCE_DIR}/Drivers" _vendored_valid)
if(_vendored_valid)
    set(STM32_DRIVERS_DIR "${PROJECT_SOURCE_DIR}/Drivers")
elseif(DEFINED _explicit_cube)
    set(STM32_DRIVERS_DIR "${_explicit_cube}/Drivers")
else()
    # Optional standard STM32CubeMX per-user installation.
    file(TO_CMAKE_PATH "$ENV{USERPROFILE}" _user_profile)
    set(_standard_cube "${_user_profile}/STM32Cube/Repository/STM32Cube_FW_F4_V1.28.3")
    _cube_validate("${_standard_cube}/Drivers" _standard_valid)
    if(NOT _standard_valid)
        _cube_path_error("${_standard_cube}")
    endif()
    set(STM32_DRIVERS_DIR "${_standard_cube}/Drivers")
endif()
message(STATUS "STM32CubeF4 drivers: ${STM32_DRIVERS_DIR}")
set(FIRMWARE_SOURCES
    Core/Src/main.c Core/Src/i2c_bus_recovery.c Core/Src/stm32f4xx_it.c Core/Src/stm32f4xx_hal_msp.c
    Core/Src/system_stm32f4xx.c Core/Src/syscalls.c Core/Src/sysmem.c
    App/Src/app.c App/Src/tmag_proto.c Drivers/Tmag3001/tmag3001_driver.c startup_stm32f411xe.s)
foreach(_source IN LISTS _hal_sources)
    list(APPEND FIRMWARE_SOURCES "${STM32_DRIVERS_DIR}/${_source}")
endforeach()
set(FIRMWARE_INCLUDE_DIRS
    "${PROJECT_SOURCE_DIR}/Core/Inc" "${PROJECT_SOURCE_DIR}/App/Inc"
    "${PROJECT_SOURCE_DIR}/Drivers/Tmag3001"
    "${STM32_DRIVERS_DIR}/STM32F4xx_HAL_Driver/Inc"
    "${STM32_DRIVERS_DIR}/STM32F4xx_HAL_Driver/Inc/Legacy"
    "${STM32_DRIVERS_DIR}/CMSIS/Device/ST/STM32F4xx/Include"
    "${STM32_DRIVERS_DIR}/CMSIS/Include")
