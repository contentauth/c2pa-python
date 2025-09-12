project(
  'c2pa-go',
  default_options: [],
)

prog_cargo = find_program('cargo')

# cargo_cmd = '@0@ build --release --target-dir "@1@"'.format(prog_cargo.full_path(), meson.current_build_dir())
# archive_dir = meson.current_build_dir()

# triple = get_option('RUST_TRIPLE')
# if triple != ''
#   cargo_cmd += ' --target @0@'.format(triple)
#   archive_dir += '/' + triple
# endif

# c2pa_go_dep = custom_target(
#   'libc2pa',
#   input: [],
#   output: ['libc2pa.a'],
#   command: [
#     'sh',
#     '-c',
#     'cd "@2@" && @0@ && cp "@3@/release/libc2pa.a" "@1@/libc2pa.a"'.format(cargo_cmd, meson.current_build_dir(), meson.current_source_dir(), archive_dir),
#   ],
#   build_by_default: true,
#   install: true,
#   install_dir : get_option('libdir'),
# )

# prog_cargo = find_program('cargo')

if get_option('default_library') == 'shared'
  cargo_cmd = '@0@ build --target-dir "@1@"'.format(prog_cargo.full_path(), meson.current_build_dir())
  archive_dir = meson.current_build_dir()

  if host_machine.system() == 'darwin'
    ext = 'dylib'
  elif host_machine.system() == 'linux'
    ext = 'so'
  else
    error('Unsupported dev system: @0@'.format(host_machine.system()))
  endif

  c2pa_go_dep = custom_target(
    'libc2pa',
    input: [],
    output: ['libc2pa.' + ext],
    command: [
      'sh',
      '-c',
      'cd "@2@" && @0@ && cp "@3@/debug/libc2pa.@4@" "@1@/libc2pa.@4@"'.format(cargo_cmd, meson.current_build_dir(), meson.current_source_dir(), archive_dir, ext),
    ],
    build_by_default: true,
    install: true,
    install_dir : get_option('libdir'),
  )
else
  cargo_cmd = '@0@ build --release --target-dir "@1@"'.format(prog_cargo.full_path(), meson.current_build_dir())
  archive_dir = meson.current_build_dir()

  triple = meson.get_external_property('RUST_TRIPLE', '')
  if triple != ''
    cargo_cmd += ' --target @0@'.format(triple)
    archive_dir += '/' + triple
  endif

  c2pa_go_dep = custom_target(
    'libc2pa',
    input: [],
    output: ['libc2pa.a'],
    command: [
      'sh',
      '-c',
      'cd "@2@" && @0@ && cp "@3@/release/libc2pa.a" "@1@/libc2pa.a"'.format(cargo_cmd, meson.current_build_dir(), meson.current_source_dir(), archive_dir),
    ],
    build_by_default: true,
    install: true,
    install_dir : get_option('libdir'),
  )
endif
