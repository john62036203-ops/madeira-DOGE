#!/usr/bin/env python3
"""A machine serial, an SMBIOS table and a system disk, like every Windows PC has (opt-in).

Programs that fingerprint the machine (anti-tamper wrappers in particular) read
the firmware tables (GetSystemFirmwareTable 'RSMB': system serial and UUID) and
open \\\\.\\PhysicalDrive0 for the disk's model and serial. On iOS the app gets
neither the device serial nor the platform UUID, IOPlatformExpertDevice may not
even be reachable (then Wine returns no SMBIOS table at all), and with no
Windows drivers there is no PhysicalDrive0. A real PC never lacks these.

With env MADEIRA_MACHINE_ID = 1:
  * system.c: madeira_machine_serial() = 20 hex digits made once per prefix and
    kept in <prefix>/.madeira-machine-id; the generated SMBIOS table uses it
    for the serial and derives a v4 UUID from it when IOKit gives none, and the
    table is built with stand-in names when IOPlatformExpertDevice is missing.
  * file.c: \\??\\PhysicalDrive0 opens a small read-only file in the prefix, and
    the usual queries about it (storage device/adapter property, SMART version
    and identify, geometry, length, device number) describe a 256 GB NVMe disk
    with that serial. Write access is refused, as for a non-admin program.
With env MADEIRA_XSTATE_AVX = 1 (system.c, arm64 init_shared_data_cpuinfo): the
XSAVE configuration in KUSER_SHARED_DATA says x87+SSE+AVX (standard layout,
0x340 bytes), matching the AVX that FEX's CPUID reports.

Same idea as NutsEmu's LGPL Wine patches 0102 (stand-in disk and machine
serial) and 0086 (AVX in the extended state on arm64); written for this tree
(wine pin 257f271, 11.4). Both switches are read through variables so the
settings catalog does not grow rows for them.

Usage: patch-wine-machine-id.py file|system <in.c> <out.c>
"""
import sys

kind, src_path, out_path = sys.argv[1], sys.argv[2], sys.argv[3]
src = open(src_path).read()


def sub(anchor, new, count=1):
    global src
    if src.count(anchor) != count:
        sys.exit("patch-wine-machine-id (%s): anchor found %d times, wanted %d:\n%s"
                 % (kind, src.count(anchor), count, anchor[:200]))
    src = src.replace(anchor, new)


if kind == "system":
    sub("""static struct smbios_prologue *create_smbios_data(void)
{
    io_service_t platform_expert;
""", r"""/* madeira-doge: tools/patch-wine-machine-id.py */
int madeira_machine_id_enabled(void)
{
    static int on = -1;
    if (on < 0)
    {
        static const char name[] = "MADEIRA_MACHINE_ID";
        const char *v = getenv( name );
        on = v && v[0] == '1';
    }
    return on;
}

const char *madeira_machine_serial(void)
{
    static char serial[21];
    static const char digits[] = "0123456789ABCDEF";
    unsigned char bytes[10];
    char *path;
    int fd, i, len;

    if (serial[0]) return serial;
    if (asprintf( &path, "%s/.madeira-machine-id", config_dir ) == -1) return "4D414445495241303031";
    if ((fd = open( path, O_RDONLY )) != -1)
    {
        len = read( fd, serial, 20 );
        close( fd );
        if (len == 20) { serial[20] = 0; free( path ); return serial; }
    }
    arc4random_buf( bytes, sizeof(bytes) );
    for (i = 0; i < 10; i++)
    {
        serial[2 * i] = digits[bytes[i] >> 4];
        serial[2 * i + 1] = digits[bytes[i] & 15];
    }
    serial[20] = 0;
    if ((fd = open( path, O_WRONLY | O_CREAT | O_TRUNC, 0644 )) != -1)
    {
        write( fd, serial, 20 );
        close( fd );
    }
    free( path );
    return serial;
}

static struct smbios_prologue *create_smbios_data(void)
{
    io_service_t platform_expert;
""")
    sub("""    platform_expert = IOServiceGetMatchingService(0, IOServiceMatching("IOPlatformExpertDevice"));
    if (!platform_expert)
        return NULL;

    cf_manufacturer""", """    platform_expert = IOServiceGetMatchingService(0, IOServiceMatching("IOPlatformExpertDevice"));
    if (!platform_expert && !madeira_machine_id_enabled())
        return NULL;
    manufacturer[0] = model[0] = serial_number[0] = 0;
    if (platform_expert) {   /* madeira-doge: machine-id builds the table without it */

    cf_manufacturer""")
    sub("""    IOObjectRelease(platform_expert);

    append_smbios_bios( &buf, manufacturer, "1.0", "01/01/2021" );
""", """    IOObjectRelease(platform_expert);
    }   /* madeira-doge */

    if (madeira_machine_id_enabled())
    {
        if (!manufacturer[0]) snprintf( manufacturer, sizeof(manufacturer), "System manufacturer" );
        if (!model[0]) snprintf( model, sizeof(model), "System Product Name" );
        if (!serial_number[0]) snprintf( serial_number, sizeof(serial_number), "%s", madeira_machine_serial() );
        if (!system_uuid.Data1 && !system_uuid.Data2 && !system_uuid.Data3 && !*(UINT64 *)system_uuid.Data4)
        {
            const char *id = madeira_machine_serial();
            BYTE *b = (BYTE *)&system_uuid;
            for (int k = 0; k < 16; k++) b[k] = (BYTE)(id[k] * 31 + id[(k + 4) % 20] * 7 + k);
            system_uuid.Data3 = (system_uuid.Data3 & 0x0fff) | 0x4000;
            system_uuid.Data4[0] = (system_uuid.Data4[0] & 0x3f) | 0x80;
        }
        fprintf( stderr, "[machine-id] madeira-doge SMBIOS: %s / %s, serial %s\\n",
                 manufacturer, model, serial_number );
    }

    append_smbios_bios( &buf, manufacturer, "1.0", "01/01/2021" );
""")
    sub("""            features[PF_SSE4_2_INSTRUCTIONS_AVAILABLE] = TRUE;
            break;
        }
    }
}

#endif /* End architecture specific feature detection for CPUs */""",
        """            features[PF_SSE4_2_INSTRUCTIONS_AVAILABLE] = TRUE;
            break;
        }
    }

    /* madeira-doge (tools/patch-wine-machine-id.py): with MADEIRA_XSTATE_AVX = 1 the XSAVE
     * configuration a real x64 CPU with AVX reports (x87, SSE, AVX; standard layout),
     * matching the AVX FEX's CPUID claims. Thread contexts carry no AVX state through
     * Wine: reads give the initial state. */
    {
        static const char name[] = "MADEIRA_XSTATE_AVX";
        const char *v = getenv( name );
        if (v && v[0] == '1')
        {
            data->XState.EnabledFeatures = data->XState.EnabledVolatileFeatures =
                (1 << XSTATE_LEGACY_FLOATING_POINT) | (1 << XSTATE_LEGACY_SSE) | (1 << XSTATE_AVX);
            data->XState.Size = data->XState.AllFeatureSize = 0x340;
            data->XState.Features[XSTATE_LEGACY_FLOATING_POINT].Offset = 0;
            data->XState.Features[XSTATE_LEGACY_FLOATING_POINT].Size = offsetof( XSAVE_FORMAT, XmmRegisters );
            data->XState.Features[XSTATE_LEGACY_SSE].Offset = offsetof( XSAVE_FORMAT, XmmRegisters );
            data->XState.Features[XSTATE_LEGACY_SSE].Size = sizeof(M128A) * 16;
            data->XState.Features[XSTATE_AVX].Offset = sizeof(XSAVE_FORMAT) + sizeof(XSAVE_AREA_HEADER);
            data->XState.Features[XSTATE_AVX].Size = sizeof(M128A) * 16;
            for (unsigned int i = 0; i <= XSTATE_AVX; i++) data->XState.AllFeatures[i] = data->XState.Features[i].Size;
            fprintf( stderr, "[xstate-avx] madeira-doge KUSER_SHARED_DATA XState: x87, SSE, AVX (0x340 bytes)\\n" );
        }
    }
}

#endif /* End architecture specific feature detection for CPUs */""")

elif kind == "file":
    sub("""/******************************************************************************
 *              NtCreateFile   (NTDLL.@)
 */""", r"""/* madeira-doge: a stand-in system disk (tools/patch-wine-machine-id.py, MADEIRA_MACHINE_ID = 1).
 * Every Windows PC has \\.\PhysicalDrive0; programs that fingerprint the machine open it
 * for the disk's model and serial. Here it is a small read-only file in the prefix, and
 * the usual queries describe a 256 GB NVMe disk whose serial is the machine serial. */
extern int madeira_machine_id_enabled(void);
extern const char *madeira_machine_serial(void);

#define MADDISK_SIZE (256ull << 30)

static const WCHAR maddisk_name[] = {'\\','?','?','\\','P','h','y','s','i','c','a','l','D','r','i','v','e','0'};

static BOOL is_maddisk_name( const UNICODE_STRING *name )
{
    unsigned int i;

    if (!name || name->Length != sizeof(maddisk_name)) return FALSE;
    for (i = 0; i < ARRAY_SIZE(maddisk_name); i++)
        if (ntdll_towupper( name->Buffer[i] ) != ntdll_towupper( maddisk_name[i] )) return FALSE;
    return TRUE;
}

static char *maddisk_path(void)
{
    char *path;
    if (asprintf( &path, "%s/.madeira-disk0", config_dir ) == -1) return NULL;
    return path;
}

static NTSTATUS maddisk_open( HANDLE *handle, ACCESS_MASK access, OBJECT_ATTRIBUTES *attr,
                              ULONG sharing, ULONG options, IO_STATUS_BLOCK *io )
{
    char *path;
    int fd;
    NTSTATUS status;

    if (access & (GENERIC_WRITE | GENERIC_ALL | FILE_WRITE_DATA | FILE_APPEND_DATA))
    {
        fprintf( stderr, "[machine-id] madeira-doge PhysicalDrive0 opened for writing: access denied\n" );
        return STATUS_ACCESS_DENIED;
    }
    if (!(path = maddisk_path())) return STATUS_NO_MEMORY;
    if ((fd = open( path, O_WRONLY | O_CREAT | O_EXCL, 0644 )) != -1)
    {
        const char *serial = madeira_machine_serial();
        write( fd, serial, strlen( serial ) );
        close( fd );
    }
    status = open_unix_file( handle, path, access, attr, 0, sharing, FILE_OPEN, options, NULL, 0 );
    fprintf( stderr, "[machine-id] madeira-doge PhysicalDrive0 -> stand-in disk, status %x\n", (unsigned)status );
    free( path );
    if (!status) io->Information = FILE_OPENED;
    return status;
}

static BOOL is_maddisk_handle( HANDLE handle )
{
    static dev_t dev;
    static ino_t ino;
    struct stat st;
    int fd, needs_close;
    BOOL ret;

    if (!ino)
    {
        char *path = maddisk_path();
        if (!path) return FALSE;
        if (!stat( path, &st )) { dev = st.st_dev; ino = st.st_ino; }
        free( path );
        if (!ino) return FALSE;
    }
    if (server_get_unix_fd( handle, 0, &fd, &needs_close, NULL, NULL )) return FALSE;
    ret = !fstat( fd, &st ) && st.st_dev == dev && st.st_ino == ino;
    if (needs_close) close( fd );
    return ret;
}

static ULONG maddisk_put_string( UCHAR *buf, ULONG size, ULONG *pos, const char *str )
{
    ULONG off = *pos, len = strlen( str ) + 1;
    if (off + len > size) return 0;
    memcpy( buf + off, str, len );
    *pos += len;
    return off;
}

/* ATA strings are space-padded, two characters to a word, the first in the high byte */
static void maddisk_ata_string( BYTE *dst, const char *str, unsigned int len )
{
    unsigned int i;
    for (i = 0; i < len; i++) dst[i ^ 1] = *str ? *str++ : ' ';
}

static NTSTATUS maddisk_ioctl( IO_STATUS_BLOCK *io, ULONG code, void *in_buffer, ULONG in_size,
                               void *out_buffer, ULONG out_size )
{
    const char *serial = madeira_machine_serial();
    ULONG info = 0;
    NTSTATUS status = STATUS_SUCCESS;
    static int logged;

    if (logged++ < 32)
        fprintf( stderr, "[machine-id] madeira-doge PhysicalDrive0 ioctl %#x in %u out %u\n",
                 (unsigned)code, (unsigned)in_size, (unsigned)out_size );
    switch (code)
    {
    case IOCTL_STORAGE_QUERY_PROPERTY:
    {
        const ULONG *query = in_buffer;  /* PropertyId, QueryType */
        if (!query || in_size < 2 * sizeof(ULONG)) return STATUS_INVALID_PARAMETER;
        if (query[0] == 0 /* StorageDeviceProperty */)
        {
            struct
            {
                ULONG Version, Size;
                UCHAR DeviceType, DeviceTypeModifier, RemovableMedia, CommandQueueing;
                ULONG VendorIdOffset, ProductIdOffset, ProductRevisionOffset, SerialNumberOffset;
                ULONG BusType, RawPropertiesLength;
            } desc = {0};
            UCHAR buf[256] = {0};
            ULONG pos = sizeof(desc) + 1;

            if (query[1] == 1 /* PropertyExistsQuery */) break;
            desc.CommandQueueing = TRUE;
            desc.ProductIdOffset = maddisk_put_string( buf, sizeof(buf), &pos, "NVMe SSD 256GB" );
            desc.ProductRevisionOffset = maddisk_put_string( buf, sizeof(buf), &pos, "1.0" );
            desc.SerialNumberOffset = maddisk_put_string( buf, sizeof(buf), &pos, serial );
            desc.BusType = 17;  /* BusTypeNvme */
            desc.Version = sizeof(desc);
            desc.Size = pos;
            memcpy( buf, &desc, sizeof(desc) );
            if (out_size < 2 * sizeof(ULONG)) return STATUS_BUFFER_TOO_SMALL;
            info = min( out_size, pos );
            memcpy( out_buffer, buf, info );
        }
        else if (query[0] == 1 /* StorageAdapterProperty */)
        {
            struct
            {
                ULONG Version, Size, MaximumTransferLength, MaximumPhysicalPages, AlignmentMask;
                BOOLEAN AdapterUsesPio, AdapterScansDown, CommandQueueing, AcceleratedTransfer;
                UCHAR BusType;
                USHORT BusMajorVersion, BusMinorVersion;
                UCHAR SrbType, AddressType;
            } adapter = { sizeof(adapter), sizeof(adapter), 0x20000, 33, 3, FALSE, FALSE, TRUE, TRUE, 17, 1, 4 };

            if (query[1] == 1) break;
            if (out_size < 2 * sizeof(ULONG)) return STATUS_BUFFER_TOO_SMALL;
            info = min( out_size, sizeof(adapter) );
            memcpy( out_buffer, &adapter, info );
        }
        else status = STATUS_NOT_SUPPORTED;
        break;
    }
    case SMART_GET_VERSION:
    {
        BYTE version[24] = { 1, 1, 0, 1 };  /* version, revision, reserved, device map: drive 0 */
        version[4] = 7;  /* capabilities: ATA ID, ATAPI ID, SMART commands */
        if (out_size < sizeof(version)) return STATUS_BUFFER_TOO_SMALL;
        memcpy( out_buffer, version, sizeof(version) );
        info = sizeof(version);
        break;
    }
    case SMART_RCV_DRIVE_DATA:
    {
        /* SENDCMDOUTPARAMS: buffer size, DRIVERSTATUS (12 bytes), then the 512-byte IDENTIFY */
        BYTE *out = out_buffer, *id;
        ULONG size = 512;
        if (out_size < 16 + 512) return STATUS_BUFFER_TOO_SMALL;
        memset( out, 0, 16 + 512 );
        memcpy( out, &size, sizeof(size) );
        id = out + 16;
        id[0] = 0x40;  /* fixed disk */
        maddisk_ata_string( id + 20, serial, 20 );
        maddisk_ata_string( id + 46, "1.0", 8 );
        maddisk_ata_string( id + 54, "NVMe SSD 256GB", 40 );
        info = 16 + 512;
        break;
    }
    case IOCTL_DISK_GET_DRIVE_GEOMETRY:
    case IOCTL_DISK_GET_DRIVE_GEOMETRY_EX:
    {
        DISK_GEOMETRY_EX geo;
        memset( &geo, 0, sizeof(geo) );
        geo.Geometry.MediaType = FixedMedia;
        geo.Geometry.TracksPerCylinder = 255;
        geo.Geometry.SectorsPerTrack = 63;
        geo.Geometry.BytesPerSector = 512;
        geo.Geometry.Cylinders.QuadPart = MADDISK_SIZE / (255 * 63 * 512);
        geo.DiskSize.QuadPart = MADDISK_SIZE;
        info = code == IOCTL_DISK_GET_DRIVE_GEOMETRY ? sizeof(DISK_GEOMETRY)
                                                     : offsetof( DISK_GEOMETRY_EX, Data );
        if (out_size < info) return STATUS_BUFFER_TOO_SMALL;
        memcpy( out_buffer, &geo, info );
        break;
    }
    case IOCTL_DISK_GET_LENGTH_INFO:
    {
        LARGE_INTEGER length;
        length.QuadPart = MADDISK_SIZE;
        if (out_size < sizeof(length)) return STATUS_BUFFER_TOO_SMALL;
        memcpy( out_buffer, &length, sizeof(length) );
        info = sizeof(length);
        break;
    }
    case IOCTL_STORAGE_GET_DEVICE_NUMBER:
    {
        ULONG number[3] = { FILE_DEVICE_DISK, 0, 0 };
        if (out_size < sizeof(number)) return STATUS_BUFFER_TOO_SMALL;
        memcpy( out_buffer, number, sizeof(number) );
        info = sizeof(number);
        break;
    }
    default:
        status = STATUS_NOT_SUPPORTED;
        break;
    }
    io->Status = status;
    io->Information = info;
    return status;
}

/******************************************************************************
 *              NtCreateFile   (NTDLL.@)
 */""")
    sub("""
    if (status == STATUS_BAD_DEVICE_TYPE)
    {
        status = server_open_file_object( handle, access, &new_attr, sharing, options );""",
        """
    if (status == STATUS_BAD_DEVICE_TYPE && !attr->RootDirectory && madeira_machine_id_enabled() &&
        is_maddisk_name( attr->ObjectName ))
    {
        status = maddisk_open( handle, access, &new_attr, sharing, options, io );
        goto done;
    }
    if (status == STATUS_BAD_DEVICE_TYPE)
    {
        status = server_open_file_object( handle, access, &new_attr, sharing, options );""")
    sub("""    if (HandleToLong( handle ) == ~0)
        return STATUS_INVALID_HANDLE;

    switch (device)
    {
    case FILE_DEVICE_BEEP:""", """    if (HandleToLong( handle ) == ~0)
        return STATUS_INVALID_HANDLE;

    if ((device == FILE_DEVICE_DISK || device == FILE_DEVICE_MASS_STORAGE) &&
        madeira_machine_id_enabled() && is_maddisk_handle( handle ))
    {
        status = maddisk_ioctl( io, code, in_buffer, in_size, out_buffer, out_size );
        if (status != STATUS_NOT_SUPPORTED)
        {
            if (event) NtSetEvent( event, NULL );
            return status;
        }
        io->Status = status;
        io->Information = 0;
        return STATUS_INVALID_DEVICE_REQUEST;
    }

    switch (device)
    {
    case FILE_DEVICE_BEEP:""")
else:
    sys.exit("usage: patch-wine-machine-id.py file|system in.c out.c")

open(out_path, "w").write(src)
print("patch-wine-machine-id: %s -> %s" % (kind, out_path))
