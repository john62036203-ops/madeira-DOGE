/* Stand-in for winegstreamer's unix side when build.sh could not compile the
 * real one (winegstreamer_unixlib_ios.c + wg_parser_apple_ios.c, or no FFmpeg
 * headers).  Both tables are a single NULL entry; virtual_ios.c's
 * ios_wg_unixlib_linked() sees that and never binds them, so winegstreamer.dll
 * gets the generic stub table exactly as it did before the media port. */
const void *winegstreamer_unix_call_funcs[1] = { 0 };
const void *winegstreamer_unix_call_wow64_funcs[1] = { 0 };
