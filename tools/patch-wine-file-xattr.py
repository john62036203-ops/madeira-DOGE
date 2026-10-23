#!/usr/bin/env python3
"""madeira-doge: file information queries list a file's extended attributes once
(NutsEmu Build 1650, Wine patch 0148-file-info-without-repeated-xattr-listing,
LGPL-2.1, "Generated-by: LLM").

On Apple systems every xattr_get/xattr_fget first lists the file's attributes
(xattr_exists) and then reads one, and fd_get_file_info/get_file_info read two
of them: a file was listed twice per query, and listing is slow on iOS. Games
and shader caches ask a file's size once per write (the C runtime appending,
DXVK writing its pipeline cache): NutsEmu measured ~40% of Mafia II's loading
threads in flistxattr (2026-10-22).

FileStandardInformation, FileInternalInformation and FileEndOfFileInformation
need no attributes and take fstat alone; the queries that do need them list the
attributes once and read only the ones that are there.

Usage: patch-wine-file-xattr.py wine/dlls/ntdll/unix/file.c [out.c]
Patches a copy; idempotent.
"""
import sys

MARK = "tools/patch-wine-file-xattr.py"

HELPER_ANCHOR = "static int xattr_get( const char *path, const char *name, void *value, size_t size )\n{"
HELPER = '''#ifdef __APPLE__
/* madeira-doge (NutsEmu 0148, tools/patch-wine-file-xattr.py): which of the two attributes
 * fd_get_file_info and get_file_info read a file has, from one listing. Each xattr_get/xattr_fget
 * lists them first, so a query listed them twice, and listing is slow on iOS: games' and DXVK's
 * file size queries (one per write) spent ~40% of their threads in flistxattr. */
enum { XATTRS_REPARSE = 1, XATTRS_DOS = 2, XATTRS_UNLISTED = 4 };

static int xattrs_present( const char *path, int fd )
{
    char xattrs[1024];
    ssize_t i = 0, ret = path ? listxattr( path, xattrs, sizeof(xattrs), 0 ) : flistxattr( fd, xattrs, sizeof(xattrs), 0 );
    int present = 0;

    if (ret == -1) return errno == ERANGE ? XATTRS_UNLISTED : 0;
    while (i < ret)
    {
        if (!strcmp( &xattrs[i], XATTR_REPARSE )) present |= XATTRS_REPARSE;
        else if (!strcmp( &xattrs[i], SAMBA_XATTR_DOS_ATTRIB )) present |= XATTRS_DOS;
        i += strlen( &xattrs[i] ) + 1;
    }
    return present;
}
#endif


'''

FD_ANCHOR = '''    attr_len = xattr_fget( fd, XATTR_REPARSE, buffer, sizeof(buffer) );
    if (attr_len >= 0 && attr_len >= sizeof(ULONG))
    {
        *attr |= FILE_ATTRIBUTE_REPARSE_POINT;
        if (reparse_tag) memcpy( reparse_tag, buffer, sizeof(ULONG) );
    }

    attr_len = xattr_fget( fd, SAMBA_XATTR_DOS_ATTRIB, attr_data, sizeof(attr_data)-1 );'''
FD_NEW = '''#ifdef __APPLE__
    {   /* madeira-doge: one listing, then only the attributes it has (NutsEmu 0148) */
        int present = xattrs_present( NULL, fd );
        if (!(present & XATTRS_UNLISTED))
        {
            if ((present & XATTRS_REPARSE)
                && (attr_len = fgetxattr( fd, XATTR_REPARSE, buffer, sizeof(buffer), 0, 0 )) >= (int)sizeof(ULONG))
            {
                *attr |= FILE_ATTRIBUTE_REPARSE_POINT;
                if (reparse_tag) memcpy( reparse_tag, buffer, sizeof(ULONG) );
            }
            if ((present & XATTRS_DOS)
                && (attr_len = fgetxattr( fd, SAMBA_XATTR_DOS_ATTRIB, attr_data, sizeof(attr_data)-1, 0, 0 )) != -1)
                *attr |= parse_samba_dos_attrib_data( attr_data, attr_len );
            return ret;
        }
    }
#endif

''' + FD_ANCHOR

PATH_ANCHOR = '''    attr_len = xattr_get( path, XATTR_REPARSE, buffer, sizeof(buffer) );
    if (attr_len >= 0 && attr_len >= sizeof(ULONG))
    {
        *attr |= FILE_ATTRIBUTE_REPARSE_POINT;
        if (reparse_tag) memcpy( reparse_tag, buffer, sizeof(ULONG) );
    }

    attr_len = xattr_get( path, SAMBA_XATTR_DOS_ATTRIB, attr_data, sizeof(attr_data)-1 );'''
PATH_NEW = '''#ifdef __APPLE__
    {   /* madeira-doge: one listing, then only the attributes it has (NutsEmu 0148) */
        int present = xattrs_present( path, -1 );
        if (!(present & XATTRS_UNLISTED))
        {
            if ((present & XATTRS_REPARSE)
                && (attr_len = getxattr( path, XATTR_REPARSE, buffer, sizeof(buffer), 0, 0 )) >= (int)sizeof(ULONG))
            {
                *attr |= FILE_ATTRIBUTE_REPARSE_POINT;
                if (reparse_tag) memcpy( reparse_tag, buffer, sizeof(ULONG) );
            }
            if ((present & XATTRS_DOS)
                && (attr_len = getxattr( path, SAMBA_XATTR_DOS_ATTRIB, attr_data, sizeof(attr_data)-1, 0, 0 )) != -1)
                *attr |= parse_samba_dos_attrib_data( attr_data, attr_len );
            else if (is_hidden_file( path ))
                *attr |= FILE_ATTRIBUTE_HIDDEN;
            return ret;
        }
    }
#endif

''' + PATH_ANCHOR

STD_OLD = '''    case FileStandardInformation:
        {
            FILE_STANDARD_INFORMATION *info = ptr;

            if (fd_get_file_info( handle, fd, options, &st, &attr, NULL ) == -1)
                status = errno_to_status( errno );
            else
            {
                fill_file_info( &st, attr, info, class );
                info->DeletePending = FALSE; /* FIXME */
            }
        }
        break;'''
STD_NEW = '''    /* madeira-doge (NutsEmu 0148): the size, links and file number need no attributes: fstat
     * only (games ask the size once per write, see xattrs_present) */
    case FileStandardInformation:
        {
            FILE_STANDARD_INFORMATION *info = ptr;

            if (fstat( fd, &st ) == -1)
                status = errno_to_status( errno );
            else
            {
                fill_file_info( &st, 0, info, class );
                info->DeletePending = FALSE; /* FIXME */
            }
        }
        break;'''

INT_OLD = '''    case FileInternalInformation:
        if (fd_get_file_info( handle, fd, options, &st, &attr, NULL ) == -1)
            status = errno_to_status( errno );
        else
            fill_file_info( &st, attr, ptr, class );
        break;'''
INT_NEW = '''    case FileInternalInformation:
        if (fstat( fd, &st ) == -1)
            status = errno_to_status( errno );
        else
            fill_file_info( &st, 0, ptr, class );
        break;'''

EOF_OLD = '''    case FileEndOfFileInformation:
        if (fd_get_file_info( handle, fd, options, &st, &attr, NULL ) == -1)
            status = errno_to_status( errno );
        else
            fill_file_info( &st, attr, ptr, class );
        break;'''
EOF_NEW = '''    case FileEndOfFileInformation:
        if (fstat( fd, &st ) == -1)
            status = errno_to_status( errno );
        else
            fill_file_info( &st, 0, ptr, class );
        break;'''


def main(src, dst):
    s = open(src, encoding="utf-8", errors="surrogateescape").read()
    if MARK not in s:
        for name, old in (("helper", HELPER_ANCHOR), ("fd", FD_ANCHOR), ("path", PATH_ANCHOR),
                          ("standard", STD_OLD), ("internal", INT_OLD), ("eof", EOF_OLD)):
            if s.count(old) != 1:
                print("patch-wine-file-xattr: anchor '%s' found %d times, expected 1" % (name, s.count(old)), file=sys.stderr)
                return 1
        s = s.replace(HELPER_ANCHOR, HELPER + HELPER_ANCHOR)
        s = s.replace(FD_ANCHOR, FD_NEW)
        s = s.replace(PATH_ANCHOR, PATH_NEW)
        s = s.replace(STD_OLD, STD_NEW)
        s = s.replace(INT_OLD, INT_NEW)
        s = s.replace(EOF_OLD, EOF_NEW)
    open(dst, "w", encoding="utf-8", errors="surrogateescape").write(s)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]))
