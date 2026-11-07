cmake_minimum_required(VERSION 3.22)
project(TMA3001_ LANGUAGES C ASM)
set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_EXTENSIONS ON)
set(CMAKE_EXPORT_COMPILE_COMMANDS ON)
if(NOT CMAKE_BUILD_TYPE)
    set(CMAKE_BUILD_TYPE Debug CACHE STRING "Build configuration" FORCE)
endif()
include(cmake/firmware_sources.cmake)
add_executable(${PROJECT_NAME} ${FIRMWARE_SOURCES})
target_include_directories(${PROJECT_NAME} PRIVATE ${FIRMWARE_INCLUDE_DIRS})
target_compile_definitions(${PROJECT_NAME} PRIVATE USE_HAL_DRIVER STM32F411xE $<$<CONFIG:Debug>:DEBUG>)
target_link_options(${PROJECT_NAME} PRIVATE
    "-T${CMAKE_CURRENT_SOURCE_DIR}/STM32F411XX_FLASH.ld"
    --specs=nano.specs "-Wl,-Map=${CMAKE_CURRENT_BINARY_DIR}/${PROJECT_NAME}.map"
    -Wl,--gc-sections -Wl,--print-memory-usage -Wl,-u,_printf_float -Wl,-u,_scanf_float)
set_property(TARGET ${PROJECT_NAME} APPEND PROPERTY LINK_DEPENDS "${CMAKE_CURRENT_SOURCE_DIR}/STM32F411XX_FLASH.ld")
target_link_libraries(${PROJECT_NAME} PRIVATE m nosys)
