import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const v = cva("inline-flex items-center gap-1 rounded-md border px-2 py-0.5 text-xs font-medium whitespace-nowrap", {
  variants: {
    variant: {
      default: "border-transparent bg-secondary text-secondary-foreground",
      outline: "text-muted-foreground",
      success: "border-transparent bg-success/10 text-success",
      warning: "border-transparent bg-warning/10 text-warning",
      destructive: "border-transparent bg-destructive/10 text-destructive",
      info: "border-transparent bg-[hsl(var(--chart-1))]/10 text-[hsl(var(--chart-1))]",
    },
  },
  defaultVariants: { variant: "default" },
});

export function Badge({ className, variant, ...p }: React.HTMLAttributes<HTMLSpanElement> & VariantProps<typeof v>) {
  return <span className={cn(v({ variant }), className)} {...p} />;
}

export function Dot({ className }: { className?: string }) {
  return <span className={cn("inline-block size-1.5 rounded-full bg-current", className)} />;
}
