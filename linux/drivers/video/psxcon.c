/*
 *	Virtual Console over PlayStation GPU.
 * FIXME: Virtual screen resolution is not supported now !!!
 */

#undef FBCONDEBUG

#include <linux/config.h>
#include <linux/module.h>
#include <linux/types.h>
#include <linux/sched.h>
#include <linux/fs.h>
#include <linux/kernel.h>
#include <linux/delay.h>	/* MSch: for IRQ probe */
#include <linux/tty.h>
#include <linux/console.h>
#include <linux/console_struct.h>
#include <linux/string.h>
#include <linux/kd.h>
#include <linux/malloc.h>
#include <linux/fb.h>
#include <linux/vt_kern.h>
#include <linux/selection.h>
#include <linux/smp.h>
#include <linux/init.h>

#include <asm/ps/libpsx.h>
#include <asm/io.h>

/* 640x480 interlace, Spleen 8x16 bitmap font: 80 columns x 30 rows. */
#define PSXVGA_SCR_H	30
#define PSXVGA_SCR_W	80

#define PSXVGA_VSCR_H	(PSXVGA_SCR_H)
#define PSXVGA_VSCR_W	(PSXVGA_SCR_W)
#define PSXVGA_FNT_H	16
#define PSXVGA_FNT_W	8

#define PSXVGA_BG_COLOR		0x000000
#define PSXVGA_CURSOR_COLOR	0xFFFFFF


static unsigned int psxvga_scrbuf[PSXVGA_VSCR_H][PSXVGA_VSCR_W];  //PSX TEXT SCREEN BUFFER
static int psxvga_cury;				// POINTER TO CURRENT STRING
static int psxvga_curx;				// POINTER TO CURRENT POSITION IN STR
static int psxvga_bottom;
static int psxvga_cursor_visible;


/*
 *  Interface used by the world
 */

static const char *psxvga_startup(void);
static void psxvga_init(struct vc_data *conp, int init);
static void psxvga_deinit(struct vc_data *conp);
static void psxvga_clear(struct vc_data *conp, int sy, int sx, int height,
		       int width);
static void psxvga_putc(struct vc_data *conp, int c, int ypos, int xpos);
static void psxvga_putcs(struct vc_data *conp, const unsigned short *s, int count,
			int ypos, int xpos);
static void psxvga_cursor(struct vc_data *conp, int mode);
static int  psxvga_scroll(struct vc_data *conp, int t, int b, int dir,
			 int count);
static void psxvga_bmove(struct vc_data *conp, int sy, int sx, int dy, int dx,
			int height, int width);
static int  psxvga_switch(struct vc_data *conp);
static int  psxvga_blank(struct vc_data *conp, int blank);
static int  psxvga_font_op(struct vc_data *conp, struct console_font_op *op);
static int  psxvga_set_palette(struct vc_data *conp, unsigned char *table);
static int  psxvga_scrolldelta(struct vc_data *conp, int lines);


/*
 *  Low Level Operations
 */


static const char *psxvga_startup (void)
{
   const char *display_desc = "PSXGPU console";
   int  x, y;
   unsigned long mode;
   for (y = 0; y < PSXVGA_VSCR_H; y++)
      for (x = 0; x < PSXVGA_VSCR_W; x++)
         psxvga_scrbuf[y][x] = 0;
         
   psxvga_cury = 0;	
   psxvga_curx = 0;
   
    /* GP1(08h): NTSC 640x480 interlace (60 Hz). */
    mode=0x08000027;
     InitGPU (mode);
   cls ();
   LoadFont ();
    psxvga_bottom = 0;
    psxvga_cursor_visible = 0;

   return  display_desc;
}


static void psxvga_init(struct vc_data *conp, int init)
{

	conp->vc_can_do_color = 0;
	conp->vc_cols = PSXVGA_VSCR_W;
	conp->vc_rows = PSXVGA_VSCR_H;
	conp->vc_x=(unsigned int)psxvga_curx;
	conp->vc_y=(unsigned int)psxvga_cury;
	conp->vc_origin=(unsigned long)0;
	conp->vc_complement_mask=0x7700;
	conp->vc_size_row=PSXVGA_VSCR_W*2;
}


static void psxvga_deinit(struct vc_data *conp)
{

}

static inline int psxvga_physical_row(int row)
{
   row += psxvga_bottom;
   if (row >= PSXVGA_VSCR_H)
      row -= PSXVGA_VSCR_H;
   return row;
}

static inline void psxvga_draw_cell(unsigned int val, int y, int x)
{
   if (y < 0 || y >= PSXVGA_VSCR_H || x < 0 || x >= PSXVGA_VSCR_W)
      return;

   line(((y * PSXVGA_FNT_H) << 16) | (x * PSXVGA_FNT_W),
        (PSXVGA_FNT_H << 16) | PSXVGA_FNT_W, PSXVGA_BG_COLOR);
   gpu_dma_gpu_idle();
   if ((val & 0xff) != ' ' && (val & 0xff) != 0) {
      print2(x * PSXVGA_FNT_W, y * PSXVGA_FNT_H, val & 0xff);
      gpu_dma_gpu_idle();
   }
}

static inline void psxvga_writew2(unsigned int val, int y, int x)
{
   if (y < 0 || y >= PSXVGA_VSCR_H || x < 0 || x >= PSXVGA_VSCR_W)
      return;
   psxvga_draw_cell(val, y, x);
   psxvga_scrbuf[psxvga_physical_row(y)][x] = val;
}

static inline void psxvga_printscreen(void)
{
   int x, y, row;

   cls();
   gpu_dma_gpu_idle();
   for (y = 0; y < PSXVGA_SCR_H; y++) {
      row = psxvga_physical_row(y);
      for (x = 0; x < PSXVGA_SCR_W; x++) {
         unsigned int val = psxvga_scrbuf[row][x];
         if ((val & 0xff) != 0 && (val & 0xff) != ' ') {
            print2(x * PSXVGA_FNT_W, y * PSXVGA_FNT_H, val & 0xff);
            gpu_dma_gpu_idle();
         }
      }
   }
   psxvga_cursor_visible = 0;
}

static inline u16 psxvga_readw(unsigned int addr)
{
   int y, x;

   if (addr >= PSXVGA_VSCR_H * PSXVGA_VSCR_W)
      return ' ';
   y = addr / PSXVGA_VSCR_W;
   x = addr % PSXVGA_VSCR_W;
   return (u16)psxvga_scrbuf[psxvga_physical_row(y)][x];
}

/* Copy one logical row, preserving overlapping source and destination. */
static inline void psxvga_memmovew(unsigned int to, unsigned int from, int count)
{
   int i;
   unsigned int dst;

   if (to == from || count <= 0)
      return;
   if (to < from) {
      for (i = 0; i < count; i++) {
         dst = to + i;
         psxvga_writew2(psxvga_readw(from + i),
                         dst / PSXVGA_VSCR_W, dst % PSXVGA_VSCR_W);
      }
   } else {
      for (i = count - 1; i >= 0; i--) {
         dst = to + i;
         psxvga_writew2(psxvga_readw(from + i),
                         dst / PSXVGA_VSCR_W, dst % PSXVGA_VSCR_W);
      }
   }
}

/* ====================================================================== */

/*  fbcon_XXX routines - interface used by the world
 *
 *  This system is now divided into two levels because of complications
 *  caused by hardware scrolling. Top level functions:
 *
 *	fbcon_bmove(), fbcon_clear(), fbcon_putc()
 *
 *  handles y values in range [0, scr_height-1] that correspond to real
 *  screen positions. y_wrap shift means that first line of bitmap may be
 *  anywhere on this display. These functions convert lineoffsets to
 *  bitmap offsets and deal with the wrap-around case by splitting blits.
 *
 *	fbcon_bmove_physical_8()    -- These functions fast implementations
 *	fbcon_clear_physical_8()    -- of original fbcon_XXX fns.
 *	fbcon_putc_physical_8()	    -- (fontwidth != 8) may be added later
 *
 *  WARNING:
 *
 *  At the moment fbcon_putc() cannot blit across vertical wrap boundary
 *  Implies should only really hardware scroll in rows. Only reason for
 *  restriction is simplicity & efficiency at the moment.
 */

static void psxvga_clear(struct vc_data *conp, int sy, int sx, int height,
                        int width)
{
   int x, y;

   if (height <= 0 || width <= 0 || sy < 0 || sx < 0 ||
       sy >= PSXVGA_VSCR_H || sx >= PSXVGA_VSCR_W)
      return;
   if (height > PSXVGA_VSCR_H - sy)
      height = PSXVGA_VSCR_H - sy;
   if (width > PSXVGA_VSCR_W - sx)
      width = PSXVGA_VSCR_W - sx;

   for (y = sy; y < sy + height; y++)
      for (x = sx; x < sx + width; x++)
         psxvga_scrbuf[psxvga_physical_row(y)][x] = ' ';

   /* Clear the entire rectangle with one GPU primitive. */
   line(((sy * PSXVGA_FNT_H) << 16) | (sx * PSXVGA_FNT_W),
        ((height * PSXVGA_FNT_H) << 16) | (width * PSXVGA_FNT_W),
        PSXVGA_BG_COLOR);
   gpu_dma_gpu_idle();
}

static void psxvga_putc(struct vc_data *conp, int c, int ypos, int xpos)
{
   psxvga_writew2 (c, ypos, xpos);
}


static void psxvga_putcs(struct vc_data *conp, const unsigned short * s, int count,
		       int ypos, int xpos)
{
   int i;

   for (i = 0; i < count; i++)
	{
      psxvga_writew2 ((scr_readw(s++)), ypos, xpos+i);
   }
}


static void psxvga_cursor(struct vc_data *conp, int mode)
{
   int x, y;

   if (psxvga_cursor_visible) {
      psxvga_draw_cell(psxvga_readw(psxvga_cury * PSXVGA_VSCR_W +
                                    psxvga_curx), psxvga_cury, psxvga_curx);
      psxvga_cursor_visible = 0;
   }
   if (mode == CM_ERASE)
      return;
   if (mode != CM_DRAW && mode != CM_MOVE)
      return;

   x = conp->vc_x;
   y = conp->vc_y;
   if (y < 0 || y >= PSXVGA_VSCR_H || x < 0 || x >= PSXVGA_VSCR_W)
      return;

   line(((y * PSXVGA_FNT_H) << 16) | (x * PSXVGA_FNT_W),
        (PSXVGA_FNT_H << 16) | PSXVGA_FNT_W, PSXVGA_CURSOR_COLOR);
   gpu_dma_gpu_idle();
   psxvga_cury = y;
   psxvga_curx = x;
   psxvga_cursor_visible = 1;
}

static int psxvga_scroll(struct vc_data *conp, int t, int b,
                         int dir, int count)
{
   int x, i, row;

   if (t < 0 || b > PSXVGA_VSCR_H || t >= b || count <= 0)
      return 0;
   if (dir != SM_UP && dir != SM_DOWN)
      return 0;
   if (count > b - t)
      count = b - t;

   /* A partial scrolling region cannot use the full-screen ring offset. */
   if (t != 0 || b != PSXVGA_VSCR_H) {
      if (dir == SM_UP) {
         psxvga_bmove(conp, t + count, 0, t, 0, b - t - count,
                      PSXVGA_VSCR_W);
         psxvga_clear(conp, b - count, 0, count, PSXVGA_VSCR_W);
      } else {
         psxvga_bmove(conp, t, 0, t + count, 0, b - t - count,
                      PSXVGA_VSCR_W);
         psxvga_clear(conp, t, 0, count, PSXVGA_VSCR_W);
      }
      return 0;
   }

   if (dir == SM_UP) {
      for (i = 0; i < count; i++) {
         row = psxvga_physical_row(i);
         for (x = 0; x < PSXVGA_VSCR_W; x++)
            psxvga_scrbuf[row][x] = ' ';
      }
      psxvga_bottom = (psxvga_bottom + count) % PSXVGA_VSCR_H;
   } else {
      psxvga_bottom =
         (psxvga_bottom + PSXVGA_VSCR_H - count) % PSXVGA_VSCR_H;
      for (i = 0; i < count; i++) {
         row = psxvga_physical_row(i);
         for (x = 0; x < PSXVGA_VSCR_W; x++)
            psxvga_scrbuf[row][x] = ' ';
      }
   }

   psxvga_printscreen();
   /* Return 0 so the VT core also updates its backing screen buffer. */
   return 0;
}

static void psxvga_bmove(struct vc_data *conp, int sy, int sx, int dy, int dx,
                         int height, int width)
{
   int y;

   if (height <= 0 || width <= 0 || sy < 0 || dy < 0 ||
       sx < 0 || dx < 0 || sy + height > PSXVGA_VSCR_H ||
       dy + height > PSXVGA_VSCR_H || sx + width > PSXVGA_VSCR_W ||
       dx + width > PSXVGA_VSCR_W)
      return;

   if (dy > sy) {
      for (y = height - 1; y >= 0; y--)
         psxvga_memmovew(dx + (dy + y) * PSXVGA_VSCR_W,
                          sx + (sy + y) * PSXVGA_VSCR_W, width);
   } else {
      for (y = 0; y < height; y++)
         psxvga_memmovew(dx + (dy + y) * PSXVGA_VSCR_W,
                          sx + (sy + y) * PSXVGA_VSCR_W, width);
   }
}

static int psxvga_switch(struct vc_data *conp)
{
   int x, y;
   u16 *screen = (u16 *)conp->vc_origin;

   if (!screen)
      return 1;
   psxvga_bottom = 0;
   for (y = 0; y < PSXVGA_VSCR_H; y++)
      for (x = 0; x < PSXVGA_VSCR_W; x++)
         psxvga_scrbuf[y][x] = scr_readw(screen + y * PSXVGA_VSCR_W + x);
   psxvga_printscreen();
   return 1;
}


static int psxvga_blank(struct vc_data *conp, int blank)
{
    return 0;
}


static int psxvga_font_op(struct vc_data *conp, struct console_font_op *op)
{
	    return -ENOSYS;
}

static int psxvga_set_palette(struct vc_data *conp, unsigned char *table)
{
 return -EINVAL;
}

static u16 *psxvga_screen_pos(struct vc_data *conp, int offset)
{
   return (u16 *)(conp->vc_origin + offset);
}

static unsigned long psxvga_getxy(struct vc_data *conp, unsigned long pos,
                                  int *px, int *py)
{
   unsigned long offset;
   int x, y;

   if (pos < conp->vc_origin || pos >= conp->vc_scr_end) {
      if (px) *px = 0;
      if (py) *py = 0;
      return conp->vc_origin;
   }
   offset = (pos - conp->vc_origin) / 2;
   x = offset % conp->vc_cols;
   y = offset / conp->vc_cols;
   if (px) *px = x;
   if (py) *py = y;
   return pos + (conp->vc_cols - x) * 2;
}

static void psxvga_invert_region(struct vc_data *conp, u16 *p, int cnt)
{

}

static int psxvga_scrolldelta(struct vc_data *conp, int lines)
{
    return 0;
}

static int psxvga_set_origin(struct vc_data *conp)
{
    return 0;
}

static void psxvga_save_screen(struct vc_data *conp)
{

}
static u8 psxvga_build_attr(struct vc_data *conp,u8 color, u8 intens, u8 blink, u8 underline, u8 reverse)
{
  u8 attr = color;
 return attr;
}

/*
 *  The console `switch' structure for the PSX GPU based console
 */
 
const struct consw psxvga_con = {
    con_startup: 	psxvga_startup, 
    con_init: 		psxvga_init,
    con_deinit: 	psxvga_deinit,
    con_clear: 		psxvga_clear,
    con_putc: 		psxvga_putc,
    con_putcs: 		psxvga_putcs,
    con_cursor: 	psxvga_cursor,
    con_scroll: 	psxvga_scroll,
    con_bmove: 		psxvga_bmove,
    con_switch: 	psxvga_switch,
    con_blank: 		psxvga_blank,
    con_font_op:	psxvga_font_op,
    con_set_palette: 	psxvga_set_palette,
    con_scrolldelta: 	psxvga_scrolldelta,
    con_set_origin: 	psxvga_set_origin,
    con_save_screen:	psxvga_save_screen,
    con_build_attr:	psxvga_build_attr,
    con_invert_region:	psxvga_invert_region,
    con_screen_pos:	psxvga_screen_pos,
    con_getxy:		psxvga_getxy
};


/*
 *  Dummy Low Level Operations
 */

static void psxvga_dummy_op(void) {}

#define DUMMY	(void *)psxvga_dummy_op
/*
struct display_switch psxvga_dummy = {
    setup:	DUMMY,
    bmove:	DUMMY,
    clear:	DUMMY,
    putc:	DUMMY,
    putcs:	DUMMY,
    revc:	DUMMY,
};
*/

/*
 *  Visible symbols for modules
 */

EXPORT_SYMBOL(psxvga_redraw_bmove);
EXPORT_SYMBOL(psxvga_redraw_clear);
EXPORT_SYMBOL(psxvga_dummy);
EXPORT_SYMBOL(psxvga_con);



