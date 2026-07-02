cmake_minimum_required(VERSION 3.16)
project(rk3588_avatar_gateway_cpp LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

find_package(OpenCV REQUIRED)

add_executable(avatar_gateway
    src/main.cpp
)

target_link_libraries(avatar_gateway PRIVATE ${OpenCV_LIBS})

if (UNIX)
    target_link_libraries(avatar_gateway PRIVATE pthread)
endif()

if (WIN32)
    target_link_libraries(avatar_gateway PRIVATE ws2_32)

    # TARGET_RUNTIME_DLLS may miss some mingw/clang runtime DLLs.
    # Copy a conservative runtime set from the active compiler bin directory.
    get_filename_component(COMPILER_BIN_DIR "${CMAKE_CXX_COMPILER}" DIRECTORY)
    set(WINDOWS_RUNTIME_HINT_DLLS
        libc++.dll
        libunwind.dll
        zlib1.dll
        libwinpthread-1.dll
        libintl-8.dll
        libiconv-2.dll
        libbz2-1.dll
        liblzma-5.dll
        libpcre2-8-0.dll
    )
    foreach(RUNTIME_DLL IN LISTS WINDOWS_RUNTIME_HINT_DLLS)
        if(EXISTS "${COMPILER_BIN_DIR}/${RUNTIME_DLL}")
            add_custom_command(
                TARGET avatar_gateway
                POST_BUILD
                COMMAND ${CMAKE_COMMAND} -E copy_if_different
                        "${COMPILER_BIN_DIR}/${RUNTIME_DLL}"
                        "$<TARGET_FILE_DIR:avatar_gateway>"
            )
        endif()
    endforeach()
endif()