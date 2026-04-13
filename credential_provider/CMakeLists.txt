cmake_minimum_required(VERSION 3.20)
project(FaceCredentialProvider LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

add_library(FaceCredentialProvider SHARED
    dll.cpp
    ClassFactory.cpp
    FaceCredentialProvider.cpp
    FaceCredential.cpp
    PipeClient.cpp
    helpers.cpp
    FaceCredentialProvider.def
)

target_compile_definitions(FaceCredentialProvider PRIVATE
    UNICODE _UNICODE
    WIN32_LEAN_AND_MEAN
)

target_link_libraries(FaceCredentialProvider PRIVATE
    credui
    secur32
    shlwapi
    ole32
    oleaut32
    advapi32
)

set_target_properties(FaceCredentialProvider PROPERTIES
    OUTPUT_NAME "FaceCredentialProvider"
    SUFFIX ".dll"
)
