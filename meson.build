project(
  'c2pa-go',
  default_options: ['default_library=static'],
)

prog_cargo = find_program('cargo')

c2pa_go_dep = custom_target(
  'libc2pa',
  input: [],
  output: ['libc2pa.a'],
  command: [prog_cargo, 'build', '--release', '--target-dir', meson.current_build_dir()],
  command: [
    'sh',
    '-c',
    'cd @2@ && @0@ build --release --target-dir @1@ && cp @1@/release/libc2pa.a @1@/libc2pa.a'.format(prog_cargo.full_path(), meson.current_build_dir(), meson.current_source_dir()),
  ],
  build_by_default: true,
)
