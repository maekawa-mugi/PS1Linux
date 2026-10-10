/* Text-only MIPS I link at VMA 0, for strict bFLT rev2 conversion. */
OUTPUT_ARCH(mips)
ENTRY(_start)
SECTIONS
{
  . = 0;
  .text : { KEEP(*(.text.start)) *(.text .text.*) }
  /DISCARD/ : { *(.got .got.*) *(.pdr) *(.reginfo) *(.MIPS.abiflags)
                 *(.gnu.attributes) *(.comment) *(.note*) *(.eh_frame*) }
}
