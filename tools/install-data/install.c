/* Native, bounded installer for Wing Commander II (Origin, 1991): the game files
 * from the user's seven 1.44 MB floppies, given as a drawer with Disk1.img to
 * Disk7.img (FAT12 images) or with the files copied from all seven disks.
 *
 * It installs as the original INSTALL.EXE does with "Save Time" (unpacked), by the
 * original's own file table INSTALL.DAT: a method per file (copy, unpack the
 * resource container, unpack the speech, unpack the program). Formats:
 * tools/origin_pak.py, its Python twin. Every disk file is checked by SHA-256
 * before use, and every file written by SHA-256 against the original installer's
 * tree (hashes.h). Not installed: the DOS installer and README.EXE. WC2.CFG holds
 * the configuration the port runs (VGA, Sound Blaster, speech on IRQ 7), as the
 * original installer writes it for those answers.
 * Destination must be new; on any failure the files created are removed. */
#include "io.h"
#include "sha256.h"
#include "hashes.h"
#include <string.h>

#define DISKS 7
#define RECORD 20
#define MAX_RECORDS 200
#define MAX_FILE 1048576UL      /* a file read or written: the largest are 374,159 and 638,494 B */
#define FILES 183               /* installed: GAMEDAT's 181, WC2.EXE, WC2.CFG */

static const char config[] = "v a904 c27\r\n";

typedef struct { File f; int open; uint32_t data; uint16_t fat[2880]; unsigned clusters; } Disk;
static Disk disk_image[DISKS];
static int images;
static unsigned char table[MAX_RECORDS * RECORD];
static char created[FILES + 4][24];
static unsigned count;
static uint16_t prefix[4096], length[4096];
static unsigned char suffix[4096], first[4096];

static uint32_t le32(const unsigned char *p)
{ return (uint32_t)p[0]|(uint32_t)p[1]<<8|(uint32_t)p[2]<<16|(uint32_t)p[3]<<24; }
static unsigned le16(const unsigned char *p) { return p[0]|(unsigned)p[1]<<8; }
static void put32(unsigned char *p, uint32_t v)
{ p[0]=(unsigned char)v; p[1]=(unsigned char)(v>>8); p[2]=(unsigned char)(v>>16); p[3]=(unsigned char)(v>>24); }
static int eq(const char *a, const char *b) { return strlen(a)==strlen(b) && !memcmp(a,b,strlen(a)); }
static int path(char *out, const char *dir, const char *name)
{
    unsigned n=strlen(dir), m=strlen(name);
    if(!n || n+m+2>512) return 0;
    memcpy(out,dir,n); if(out[n-1]!=':' && out[n-1]!='/') out[n++]='/';
    memcpy(out+n,name,m+1); return 1;
}
static const Hash *find(const Hash *t, unsigned n, const char *name)
{
    unsigned k;
    for(k=0;k<n;k++) if(eq(t[k].name,name)) return &t[k];
    return 0;
}
static int hashed(const Hash *h, const unsigned char *p, uint32_t n)
{
    SHA256 s; unsigned char out[32];
    if(!h) return 0;
    sha_init(&s); sha_update(&s,p,n); sha_final(&s,out);
    return !memcmp(out,h->sha,32);
}

/* FAT12 image of one 1.44 MB disk: the root directory and the first FAT. */
static int open_image(Disk *d, const char *source, unsigned n)
{
    static char lower[]="disk0.img", upper[]="Disk0.img", ima[]="Disk0.ima";
    static unsigned char b[512*9];
    char target[512];
    unsigned bps, spc, reserved, fats, roots, spf, k;
    lower[4]=upper[4]=ima[4]=(char)('1'+n);
    if(!(path(target,source,upper) && io_open(&d->f,target,0)) && !(path(target,source,lower) && io_open(&d->f,target,0))
       && !(path(target,source,ima) && io_open(&d->f,target,0))) return 0;
    d->open=1;
    if(!io_read(&d->f,b,512)) return 0;
    bps=le16(b+11); spc=b[13]; reserved=le16(b+14); fats=b[16]; roots=le16(b+17); spf=le16(b+22);
    if(bps!=512 || spc!=1 || !reserved || fats<1 || fats>2 || roots!=224 || spf!=9) return 0;
    d->data=(reserved+fats*spf)*512UL+roots*32UL;
    if(!io_seek(&d->f,reserved*512UL) || !io_read(&d->f,b,spf*512)) return 0;
    d->clusters=(unsigned)((d->f.size-d->data)/512);
    if(d->clusters>2880) return 0;
    for(k=0;k<d->clusters+2 && k<2880;k++) {
        unsigned e=k+k/2;
        d->fat[k]=(uint16_t)(k&1?le16(b+e)>>4:le16(b+e)&0xfff);
    }
    return 1;
}
/* The whole file NAME of disk N (1..7) into buf; its size, 0 when missing or bad. */
static uint32_t read_image(Disk *d, const char *name, unsigned char *buf)
{
    static unsigned char root[224*32];
    unsigned char *e=0;
    char n83[11];
    unsigned k, j, c;
    uint32_t size, got=0;
    memset(n83,' ',11);
    for(k=0,j=0;name[k] && name[k]!='.';k++) if(j<8) n83[j++]=name[k];
    if(name[k]=='.') for(k++,j=8;name[k];k++) if(j<11) n83[j++]=name[k];
    if(!io_seek(&d->f,d->data-sizeof root) || !io_read(&d->f,root,sizeof root)) return 0;
    for(k=0;k<224;k++) if(!memcmp(root+32*k,n83,11) && !(root[32*k+11]&0x18)) { e=root+32*k; break; }
    if(!e) return 0;
    size=le32(e+28); c=le16(e+26);
    if(!size || size>MAX_FILE) return 0;
    while(got<size) {
        uint32_t n=size-got>512?512:size-got;
        if(c<2 || c>=d->clusters+2 || !io_seek(&d->f,d->data+(c-2)*512UL) || !io_read(&d->f,buf+got,n)) return 0;
        got+=n; c=d->fat[c];
    }
    return c>=0xff8?size:0;
}
static uint32_t read_disk_file(const char *source, unsigned n, const char *name, unsigned char *buf)
{
    File f={0}; char target[512]; uint32_t size;
    if(images) return n>=1 && n<=DISKS ? read_image(&disk_image[n-1],name,buf) : 0;
    if(!path(target,source,name) || !io_open(&f,target,0)) return 0;
    size=f.size;
    if(!size || size>MAX_FILE || !io_read(&f,buf,size)) size=0;
    io_close(&f);
    return size;
}

/* LZW: LSB-first codes of 9..12 bits, 256 resets, 257 ends, no early width change. */
static int lzw(const unsigned char *in, uint32_t n, unsigned char *out, uint32_t size)
{
    uint32_t pos=0, bits=0, got=0;
    unsigned nb=0, width=9, next=258, k;
    int prev=-1;
    for(k=0;k<256;k++) { length[k]=1; suffix[k]=first[k]=(unsigned char)k; }
    for(;;) {
        unsigned code, c, l;
        while(nb<width) { if(pos>=n) return 0; bits|=(uint32_t)in[pos++]<<nb; nb+=8; }
        code=bits&((1u<<width)-1); bits>>=width; nb-=width;
        if(code==256) { next=258; width=9; prev=-1; continue; }
        if(code==257) return got==size;
        if(code<next && (code<256 || code>257)) c=code;
        else if(code==next && prev>=0) c=(unsigned)prev;
        else return 0;
        l=length[c]+(c!=code);
        if(l>size-got) return 0;
        if(c!=code) out[got+l-1]=first[c];
        for(k=length[c];k;k--) { out[got+k-1]=c<256?(unsigned char)c:suffix[c]; if(c>=256) c=prefix[c]; }
        if(prev>=0 && next<4096) {
            prefix[next]=(uint16_t)prev; suffix[next]=out[got]; first[next]=first[prev];
            length[next]=(uint16_t)(length[prev]+1); next++;
        }
        prev=(int)code; got+=l;
        if(next>=(1u<<width) && width<12) width++;
    }
}
/* Speech: 8-bit PCM in 4-bit deltas (tools/origin_pak.py speech). */
static void speech(const unsigned char *in, uint32_t n, unsigned char *out)
{
    int s=in[0], lev=0; uint32_t k, o=1;
    out[0]=in[0];
    for(k=1;k<n;k++) {
        unsigned h;
        for(h=0;h<2;h++) {
            unsigned code=h?in[k]&15:in[k]>>4, m=code&7;
            int d=(int)(m<<lev)+(lev?1<<(lev-1):0);
            s=code&8?s-d:s+d; if(s<0) s=0; if(s>255) s=255;
            out[o++]=(unsigned char)s;
            lev=m>=5?(lev<3?lev+1:3):m==0?(lev?lev-1:0):lev;
        }
    }
}

/* The resource container with every entry unpacked (tools/origin_pak.py unpack).
 * Returns the output size, 0 on bad data; out NULL measures only. */
#define MAX_ENTRIES 512
static uint32_t offs[MAX_ENTRIES], ends[MAX_ENTRIES], at[MAX_ENTRIES];
static unsigned char flags[MAX_ENTRIES];
static uint32_t container(const unsigned char *b, uint32_t n, int voice, unsigned char *out)
{
    uint32_t firstoff=n, head, body;
    unsigned ents=0, k, j;
    if(n<8 || le32(b)!=n) return 0;
    for(k=4;k<firstoff;k+=4) {
        uint32_t v;
        if(k+4>n || ents>=MAX_ENTRIES) return 0;
        v=le32(b+k); offs[ents]=v&0xffffff; flags[ents]=(unsigned char)(v>>24);
        if(offs[ents]>n) return 0;
        if(offs[ents] && offs[ents]<firstoff) firstoff=offs[ents];
        ents++;
    }
    for(k=0;k<ents;k++) {
        uint32_t e=n;
        for(j=0;j<ents;j++) if(offs[j]>offs[k] && offs[j]<e) e=offs[j];
        ends[k]=offs[k]&&offs[k]<n?e:offs[k];
    }
    head=4+4*ents; body=head;
    for(k=0;k<ents;k++) {
        uint32_t o=offs[k], len=ends[k]-o, size;
        if(!o || flags[k]==0xff) continue;
        for(j=0;j<k;j++) if(offs[j]==o && flags[j]!=0xff) break;
        if(j<k) { at[k]=at[j]; continue; }
        at[k]=body;
        if(flags[k]==0xe0 && voice) size=len?2*len-1:0;
        else if(flags[k]&0xc0) size=len;
        else {
            if(len<4) return 0;
            size=le32(b+o);
            if(size>MAX_FILE) return 0;
            if(voice) size=size?2*size-1:0;
        }
        if((voice && !size) || size>MAX_FILE-body) return 0;
        if(out) {
            if(flags[k]==0xe0 && voice) speech(b+o,len,out+body);
            else if(flags[k]&0xc0) memcpy(out+body,b+o,len);
            else if(voice) {                   /* LZW behind the samples, then speech */
                uint32_t l=(size+1)/2;
                if(!lzw(b+o+4,len-4,out+body+l-1,l)) return 0;
                speech(out+body+l-1,l,out+body);
            } else if(!lzw(b+o+4,len-4,out+body,size)) return 0;
        }
        body+=size;
    }
    if(out) {
        put32(out,body);
        for(k=0;k<ents;k++) {
            uint32_t v;
            if(!offs[k]) v=(uint32_t)flags[k]<<24;
            else if(flags[k]==0xff) {
                if(offs[k]==n) v=body;
                else {
                    for(j=0;j<ents;j++) if(offs[j]==offs[k] && flags[j]!=0xff) break;
                    if(j==ents) return 0;
                    v=at[j];
                }
                v|=0xffUL<<24;
            } else v=at[k]|(uint32_t)(flags[k]|0xc0)<<24;
            put32(out+4+4*k,v);
        }
    }
    return body;
}

static int write_file(const char *dest, const char *name, const unsigned char *p, uint32_t n)
{
    File f={0}; char target[512];
    if(!path(target,dest,name) || io_exists(target) || !io_open(&f,target,1)) return 0;
    memcpy(created[count++],name,strlen(name)+1);
    if(!io_write(&f,p,n)) { io_close(&f); return 0; }
    return io_close(&f);
}

int install_data(const char *source, const char *dest, const char *temp)
{
    static unsigned char *in, *out;
    char target[512], name[14], file[24];
    unsigned k, records=0, files=0;
    uint32_t n;
    int ok=0;
    (void)temp; count=0; images=0;
    if(io_exists(dest)) { io_message("Destination exists; refusing to replace files."); return 20; }
    in=io_alloc(MAX_FILE); out=io_alloc(MAX_FILE);
    if(!in || !out) { io_message("Not enough memory: the installer needs 2 MB."); goto done; }
    io_message("Checking the Wing Commander II disks...");
    if(!path(target,source,"INSTALL.DAT") || !io_exists(target)) {
        for(k=0;k<DISKS;k++) if(!open_image(&disk_image[k],source,k)) {
            io_message("Disk images or files missing. Need Disk1.img to Disk7.img, or the files of all seven disks in one drawer.");
            goto done;
        }
        images=1;
    }
    n=read_disk_file(source,1,"INSTALL.DAT",in);
    if(!n || n>sizeof table || n%RECORD || !hashed(find(disk,sizeof disk/sizeof *disk,"INSTALL.DAT"),in,n)) {
        io_message("Unsupported disks: INSTALL.DAT is missing or changed. Use the Wing Commander II floppies.");
        goto done;
    }
    memcpy(table,in,n);
    records=(unsigned)(n/RECORD);
    if(!io_mkdir(dest)) goto done;
    memcpy(created[count++],"",1);
    if(!path(target,dest,"GAMEDAT") || !io_mkdir(target)) goto done;
    memcpy(created[count++],"GAMEDAT",8);
    io_message("Installing Wing Commander II...");
    for(k=0;k<records;k++) {
        const unsigned char *r=table+k*RECORD;
        unsigned d=r[13], method=r[14], j;
        uint32_t size, got, skip=0;
        if(!r[0]) break;
        if(io_cancelled()) goto done;
        memcpy(name,r,13); name[13]=0;
        for(j=0;name[j];j++) if(!((name[j]>='A' && name[j]<='Z') || (name[j]>='0' && name[j]<='9') || name[j]=='.' || name[j]=='_')) goto done;
        if(eq(name,"INSTALL.DAT") || eq(name,"INSTALL.EXE") || eq(name,"README.LZC")) continue;  /* DOS programs */
        size=read_disk_file(source,d,name,in);
        if(!size || !hashed(find(disk,sizeof disk/sizeof *disk,name),in,size)) {
            io_message("A disk file is missing or damaged. Use the Wing Commander II floppies:");
            io_message(name);
            goto done;
        }
        if(method==1 || method==7) { memcpy(out,in,size); got=size; }
        else if(method==2 || method==3 || method==8) {
            got=container(in,size,method==8,0);
            if(!got || got>MAX_FILE || container(in,size,method==8,out)!=got) got=0;
        } else if(method==6 && eq(name,"WC2.LZC")) {
            got=container(in,size,0,out);      /* one entry: its data is the program */
            if(got<12 || le32(out+4)!=(0xe0UL<<24|8)) got=0;
            else { got-=8; skip=8; }
        } else got=0;
        if(method==6) memcpy(file,"WC2.EXE",8);
        else { memcpy(file,"GAMEDAT/",8); memcpy(file+8,name,14); }
        if(!got || !hashed(find(installed,sizeof installed/sizeof *installed,file),out+skip,got)) {
            io_message("Unpacking failed:"); io_message(file); goto done;
        }
        if(!write_file(dest,file,out+skip,got)) { io_message("Write failed:"); io_message(file); goto done; }
        files++;
    }
    if(!hashed(find(installed,sizeof installed/sizeof *installed,"WC2.CFG"),(const unsigned char *)config,sizeof config-1)
       || !write_file(dest,"WC2.CFG",(const unsigned char *)config,sizeof config-1)) goto done;
    files++;
    if(files!=FILES) { io_message("Unexpected file count in INSTALL.DAT."); goto done; }
    ok=1; io_message("Installed the 183 Wing Commander II files.");
done:
    for(k=0;k<DISKS;k++) if(disk_image[k].open) { io_close(&disk_image[k].f); disk_image[k].open=0; }
    io_free(in); io_free(out); in=out=0;
    if(!ok) {
        while(count) {
            --count;
            if(!created[count][0]) io_remove(dest);
            else if(path(target,dest,created[count])) io_remove(target);
        }
        io_message("Installation failed or cancelled; existing installations were not changed.");
    }
    return ok?0:20;
}
