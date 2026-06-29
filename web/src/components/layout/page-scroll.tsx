"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

type WheelTargetRef = React.RefObject<HTMLElement | null>;

const WHEEL_DELTA_LINE = 1;
const WHEEL_DELTA_PAGE = 2;
const WHEEL_LINE_HEIGHT = 40;

function getWheelDeltaY(event: React.WheelEvent<HTMLElement>, scrollTarget: HTMLElement) {
  if (event.deltaMode === WHEEL_DELTA_LINE) {
    return event.deltaY * WHEEL_LINE_HEIGHT;
  }

  if (event.deltaMode === WHEEL_DELTA_PAGE) {
    return event.deltaY * scrollTarget.clientHeight;
  }

  return event.deltaY;
}

function canScrollY(element: HTMLElement, deltaY: number) {
  if (element.scrollHeight <= element.clientHeight + 1) {
    return false;
  }

  if (deltaY < 0) {
    return element.scrollTop > 0;
  }

  if (deltaY > 0) {
    return element.scrollTop + element.clientHeight < element.scrollHeight - 1;
  }

  return false;
}

function isScrollableY(element: HTMLElement) {
  const { overflowY } = window.getComputedStyle(element);
  return /(auto|scroll|overlay)/.test(overflowY);
}

function findScrollableAncestor(target: Element | null, boundary: HTMLElement, deltaY: number) {
  let node = target;

  while (node && node !== boundary) {
    if (node instanceof HTMLElement && isScrollableY(node) && canScrollY(node, deltaY)) {
      return node;
    }
    node = node.parentElement;
  }

  return null;
}

function useWheelFallback(targetRef?: WheelTargetRef) {
  return React.useCallback(
    (event: React.WheelEvent<HTMLElement>) => {
      const scrollTarget = targetRef?.current;
      if (!scrollTarget || event.defaultPrevented || event.deltaY === 0) {
        return;
      }

      const deltaY = getWheelDeltaY(event, scrollTarget);
      if (deltaY === 0) {
        return;
      }

      const boundary = event.currentTarget;
      const target = event.target instanceof Element ? event.target : null;
      if (findScrollableAncestor(target, boundary, deltaY)) {
        return;
      }

      if (!canScrollY(scrollTarget, deltaY)) {
        return;
      }

      event.preventDefault();
      scrollTarget.scrollBy({ top: deltaY, behavior: "auto" });
    },
    [targetRef],
  );
}

export function PageShell({
  className,
  children,
  ...props
}: React.ComponentProps<"section">) {
  return (
    <section className={cn("min-w-0 space-y-5 pb-6", className)} {...props}>
      {children}
    </section>
  );
}

export function PageViewportShell({
  className,
  children,
  wheelTargetRef,
  onWheelCapture,
  ...props
}: React.ComponentProps<"section"> & {
  wheelTargetRef?: WheelTargetRef;
}) {
  const handleWheelCapture = useWheelFallback(wheelTargetRef);

  return (
    <section
      className={cn("min-h-0 min-w-0", className)}
      onWheelCapture={(event) => {
        onWheelCapture?.(event);
        handleWheelCapture(event);
      }}
      {...props}
    >
      {children}
    </section>
  );
}

export const ScrollRegion = React.forwardRef<
  HTMLDivElement,
  React.ComponentProps<"div">
>(function ScrollRegion({ className, children, ...props }, ref) {
  return (
    <div
      ref={ref}
      className={cn(
        "min-h-0 overflow-y-auto overscroll-contain [scrollbar-color:rgba(120,113,108,.45)_transparent] [scrollbar-width:thin] [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-stone-400/45 [&::-webkit-scrollbar-track]:bg-transparent",
        className,
      )}
      {...props}
    >
      {children}
    </div>
  );
});
