#---------- print text ----------

#include <asm/regdef.h>
#include <asm/ps/gpu.h>

#define	CLUT_ID(page, x, y)	(( page & 0xf ) << 2 )  | (( page & 0x10 ) << 10 ) | ( x >> 4 ) | ( y << 6 )

/* Keep the 4-bit font texture and its CLUT outside the 640x480 display. */
#define FONT_TEX_X  704
#define FONT_CLUT_X 704
#define FONT_CLUT_Y 384
#define	TAG( adr, size ) 	.word	adr + ( size << 24 )
#define	END_TAG( size )		.word	0xffffff + ( size << 24 )

#define  GPU_PRIM_COMMAND	0
#define  GPU_PRIM_POLYGON	1
#define  GPU_PRIM_LINE		 2
#define  GPU_PRIM_SPRITE 	3
#define  GPU_PRIM_TRANSFER 4
#define  GPU_PRIM_ENVIRON  7

			.global	cls
cls:	subu	sp,sp,4
			sw		ra,(sp)
			la		a0,back
			jal	 SendList
			lw		ra,(sp)
			addu	sp,sp,4
			jr		ra

prim_cls:	END_TAG( 3 )
  		.byte	0x0, 0x0, 0x0, 0x02			# rgb
			.short	0, 0										# x, y  
			.short	512, 512								# w, h
	  		
back:
      TAG( back2, 3 )
      .word 0x02000000
      .word 0x000003c0
      .word 0x010000fe


back2:   END_TAG( 8 )   	# Primitive of gouroud 4 point polygon
      .word  0x38000000    # Type + bgr    top left
			.short 0,0
      .word  0x00000000   # bgr           top right
			.short 0,511
      .word  0x00000000    # bgr           bottom left
			.short 659,0
      .word  0x00000000    # bgr           bottom right
			.short 659,511


			.global	LoadFont

LoadFont:   subu	sp,sp,4
			sw		 ra,(sp)
			
			la 		a0,font+64      # transfer image data to VRAM
      li 		a1,FONT_TEX_X  # x = 704, y = 0 (outside framebuffer)
    	li 		a2,64+(128<<16)	# w = 64 halfwords (256 px), h = 128
      li 		a3,64*128/2			# word count
      jal 	 mem2vram

      la 		a0,font+20      # transfer clut data to VRAM
      
#			lh		v0,(a0)					# transparent or not
#			or		v0,v0,0x8000
#			sh		v0,(a0)
			
      li 		a1,FONT_CLUT_X+(FONT_CLUT_Y<<16) # x = 704, y = 384
      li 		a2,16+(1<<16)		# w = 16, h = 1
      li 		a3,8
      jal 	 mem2vram

      # GP0(01h) invalidates the texture cache after the font and CLUT
      # uploads. GP1(01h) used by mem2vram resets commands instead.
      # Synchronize first so renderers see the freshly loaded glyphs.
      jal    gpu_dma_gpu_idle
      nop
      jal    WaitGPU
      nop
      li     t2,PSX_HW
      li     t1,0x01000000
      sw     t1,GPU0(t2)

	lw		ra,(sp)
	addu	sp,sp,4
	jr		ra
	
			.global	set_tPage
			.global	putsprite

#---------- print text -----------------------------------------
# a0: void *pimitive

set_tPage:	addu	v0,a0,8
			sw		v0,(a0)
			li		v1,1
			sb		v1,3(a0)
			li		v1,0xE1000005               	# tPage for font
			sw		v1,4(a0)
			jr		ra
			

#---------- print text -----------------------------------------
# a0: char *text
# a1: *primitive
			
			.global	print_txt

print_txt:	subu	sp,sp,12
			sw		s0,(sp)
			sw		s1,4(sp)
			sw		ra,8(sp)

			move	s0,a0					# txt-pointer
			move	a0,a1					# prim-tab
			li		a1,0					 # x
			li		a2,0					 # y

print_inf1:	lbu		a3,(s0)						# Zeichen
			addu	s0,s0,1
			beqz	a3,print_end
			xor	 v0,a3,0x80
			bnez	v0,no_control
			lbu	 a1,(s0)					 # new x
			lbu	 a2,1(s0)					# new y
			sll	 a1,a1,3					# x * 8
			sll	 a2,a2,4					# y * 16
			addu	s0,s0,2
			j		 print_inf1

no_control: 		jal		print
			move	a0,v0			// next primitive address
			addu	a1,a1,8						# x += 8
			j		print_inf1

print_end:  
			li		t0,0x04ffffff
			sw		t0,-20(a0)	// end of primitives list

			lw		s0,(sp)
			lw		s1,4(sp)
			lw		ra,8(sp)

			addu		sp,sp,12
			jr		ra

            .global line

#---------- line (untextured variable-size GPU rectangle) ----------
# a0: (y << 16) | x
# a1: (height << 16) | width
# a2: RGB888 (low 24 bits)
#
# PCSX-Redux diagnosis: send the rectangle over GP0 PIO, just like the
# textured glyphs in print2. Mixing DMA2 linked-list rectangles with GP0
# PIO glyphs can interleave commands if DMA mode/queue synchronization
# differs between emulators. Sending both in the same stream also makes
# the full console background clear deterministic.
line:
      subu   sp,sp,4
      sw     ra,0(sp)

      jal    gpu_dma_gpu_idle
      nop
      jal    WaitIdle
      nop

      li     t3,PSX_HW
      li     t0,0x00ffffff
      and    t4,a2,t0
      lui    t0,0x6000
      or     t4,t4,t0            # GP0(60h) + untextured RGB

      # GPUSTAT bit 26 guarantees readiness for a word, not an entire
      # multiword packet. Poll before EACH GP0 parameter.
      jal    WaitIdle
      nop
      sw     t4,GPU0(t3)
      jal    WaitIdle
      nop
      sw     a0,GPU0(t3)         # position (x, y)
      jal    WaitIdle
      nop
      sw     a1,GPU0(t3)         # dimensions (width, height)
      jal    WaitIdle
      nop

      lw     ra,0(sp)
      addu   sp,sp,4
      jr     ra
      nop

/*
 * GP0(80h) VRAM-to-VRAM copy, for 8x16 GPU-console scanline strips.
 * a0 = src (y<<16|x), a1 = dst, a2 = dimensions (h<<16|w).
 * Keep all four GP0 words on the same PIO path as print2()/line().
 */
            .global psxvga_copy_vram
psxvga_copy_vram:
      subu   sp,sp,4
      sw     ra,0(sp)
      jal    gpu_dma_gpu_idle
      nop
      li     t3,PSX_HW
      li     t4,0x80000000
      jal    WaitIdle
      nop
      sw     t4,GPU0(t3)
      jal    WaitIdle
      nop
      sw     a0,GPU0(t3)
      jal    WaitIdle
      nop
      sw     a1,GPU0(t3)
      jal    WaitIdle
      nop
      sw     a2,GPU0(t3)
      jal    WaitIdle
      nop
      lw     ra,0(sp)
      addu   sp,sp,4
      jr     ra
      nop

			.global	putsprite


#---------- print -----------------------
// creates primitive at prim-address
# a0: prim-address, 20 bytes per character
# a1: x
# a2: y
# a3: char
// Output:
//	v0 -- address of the next primitive	

print:
			addu	v0,a0,5*4				# prim needs 4+1 words
      sw		v0,(a0)					# link to next prim
      li		t0,4
      sb		t0,3(a0)         # prim - size

// set font color
      li		t0,0x64808080
      sw		t0,4(a0)
// set x y position
      sh		a1,8(a0)				# x
      sh		a2,10(a0)       # y
// set char decomposition (u,v)
      and	 t0,a3,0x1f
      sll	 t0,t0,3				 # * 8
      sb		t0,12(a0)			 # u
      srl	 t0,a3,5
      sll	 t0,t0,4	 			# * 16
      sb		t0,13(a0)	 		# v
// set clut id      
      li		t0,CLUT_ID( 0, FONT_CLUT_X, FONT_CLUT_Y )
      sh		t0,14(a0)
// set font size
      li		t0,0x00100008 	# w = 8, h = 16
      sw		t0,16(a0)

      jr		ra

			.global print2
#---------- print -----------------------
# a0: x
# a1: y
# a2: char

print2:     subu	sp,sp,4
			sw		ra,(sp)
			la		t0,pp1

      sh		a0,8(t0)				# x
      sh		a1,10(t0)       # y
      and	 t1,a2,0x1f
      sll	 t1,t1,3				 # * 8
      sb		t1,12(t0)			 # u
      srl	 t1,a2,5
      sll	 t1,t1,4	 			# * 16
      sb		t1,13(t0)	 	# v

      # PCSX-Redux test: send sprite command words through GP0 PIO
      # instead of starting a new DMA2 linked-list for every glyph.
      # Avoid reliance on mutable DMA tags in a shared packet buffer.
      jal    gpu_dma_gpu_idle
      nop
      jal    WaitIdle
      nop
      # t3 holds GPU base, t5 the packet base, and t4 the command word.
      # WaitIdle() uses t0..t2, so all three survive each readiness poll.
      li     t3,PSX_HW
      la     t5,pp1
      li     t4,0xE100040B     # 4-bit font at x=704,y=0; DFE=1 for 480i
      jal    WaitIdle
      nop
      sw     t4,GPU0(t3)

      # pp1+0 is the DMA tag. Skip it for PIO and check GPUSTAT bit26
      # before EVERY payload word, not merely once per four-word sprite.
      lw     t4,4(t5)          # GP0(64h): textured sprite
      jal    WaitIdle
      nop
      sw     t4,GPU0(t3)
      lw     t4,8(t5)          # screen x,y
      jal    WaitIdle
      nop
      sw     t4,GPU0(t3)
      lw     t4,12(t5)         # UV and CLUT
      jal    WaitIdle
      nop
      sw     t4,GPU0(t3)
      lw     t4,16(t5)         # width, height
      jal    WaitIdle
      nop
      sw     t4,GPU0(t3)

      jal    WaitIdle
      nop

			lw		ra,(sp)
			addu	sp,sp,4
      jr		ra
      nop

			.global	print_prim
			
print_prim:	TAG( pp1, 1 )
			.word	0xE100000B              	# tPage for font
pp1:	END_TAG( 4 )
    	.byte	0x80, 0x80, 0x80, 0x64		# rgb, font color
			.short	0, 0						 # x, y
			.byte	 0, 0						// u, v - char decomposition
			.short	CLUT_ID( 0, FONT_CLUT_X, FONT_CLUT_Y )
			.short	8, 16  					# w, h
	.global	rct0
rct0:	TAG(rct1,1)
	.word	0x60FFFFFF
rct1:	END_TAG( 2 )
	.short	100,100 	    		
	.short	100,100 	    		

			.balign	4
font:
#include "font/font.S"
			.balign	2048
the_end:
			


