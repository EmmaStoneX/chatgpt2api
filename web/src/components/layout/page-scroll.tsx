"use client";

import * as React from "react";

import { cn } from "@/lib/utils";

type WheelTargetRef = React.RefObject<HTMLElement | null>;

const WHEEL_DELTA_LINE = 1;
const WHEEL_DELTA_PAGE = 2;
const WHEEL_LINE_HEIGHT = 40;
const WHEEL_ROUTED_FLAG = "__chatgpt2apiWheelRouted";

type WheelEventLike = {
  deltaY: number;
  deltaMode: number;
  defaultPrevented: boolean;
  target: EventTarget | null;
  preventDefault: () => void;
};

type RoutedWheelEvent = WheelEventLike & {
  [WHEEL_ROUTED_FLAG]?: boolean;
};

function getWheelDeltaY(deltaY: number, deltaMode: number, scrollTarget: HTMLElement) {
  if (deltaMode === WHEEL_DELTA_LINE) {
    return deltaY * WHEEL_LINE_HEIGHT;
  }

  if (deltaMode === WHEEL_DELTA_PAGE) {
    return deltaY * scrollTarget.clientHeight;
  }

  return deltaY;
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

function routeWheelToTarget(event: WheelEventLike, boundary: HTMLElement, scrollTarget: HTMLElement | null) {
  const routedEvent = event as RoutedWheelEvent;
  if (routedEvent[WHEEL_ROUTED_FLAG] || !scrollTarget || event.defaultPrevented || event.deltaY === 0) {
    return false;
  }

  const deltaY = getWheelDeltaY(event.deltaY, event.deltaMode, scrollTarget);
  if (deltaY === 0) {
    return false;
  }

  const target = event.target instanceof Element ? event.target : null;
  if (findScrollableAncestor(target, boundary, deltaY)) {
    return false;
  }

  if (!canScrollY(scrollTarget, deltaY)) {
    return false;
  }

  event.preventDefault();
  routedEvent[WHEEL_ROUTED_FLAG] = true;
  scrollTarget.scrollBy({ top: deltaY, behavior: "auto" });
  return true;
}

function useWheelFallback(targetRef?: WheelTargetRef) {
  return React.useCallback(
    (event: React.WheelEvent<HTMLElement>) => {
      const nativeEvent = event.nativeEvent as RoutedWheelEvent;
      if (nativeEvent[WHEEL_ROUTED_FLAG]) {
        return;
      }
      if (routeWheelToTarget(event, event.currentTarget, targetRef?.current ?? null)) {
        nativeEvent[WHEEL_ROUTED_FLAG] = true;
      }
    },
    [targetRef],
  );
}

function useNativeWheelFallback(containerRef: React.RefObject<HTMLElement | null>, targetRef?: WheelTargetRef) {
  React.useEffect(() => {
    const container = containerRef.current;
    if (!container || !targetRef) {
      return;
    }

    const handleWheel = (event: WheelEvent) => {
      routeWheelToTarget(event, container, targetRef.current);
    };

    container.addEventListener("wheel", handleWheel, { capture: true, passive: false });
    return () => {
      container.removeEventListener("wheel", handleWheel, { capture: true });
    };
  }, [containerRef, targetRef]);
}

function getDocumentScrollTarget() {
  if (typeof document === "undefined") {
    return null;
  }
  const scrollElement = document.scrollingElement || document.documentElement;
  return scrollElement instanceof HTMLElement ? scrollElement : null;
}

function useDocumentWheelFallback() {
  return React.useCallback((event: React.WheelEvent<HTMLElement>) => {
    const nativeEvent = event.nativeEvent as RoutedWheelEvent;
    if (nativeEvent[WHEEL_ROUTED_FLAG]) {
      return;
    }
    if (routeWheelToTarget(event, event.currentTarget, getDocumentScrollTarget())) {
      nativeEvent[WHEEL_ROUTED_FLAG] = true;
    }
  }, []);
}

function useNativeDocumentWheelFallback() {
  React.useEffect(() => {
    const handleWheel = (event: WheelEvent) => {
      if (!document.body) {
        return;
      }
      routeWheelToTarget(event, document.body, getDocumentScrollTarget());
    };

    document.addEventListener("wheel", handleWheel, { capture: true, passive: false });
    return () => {
      document.removeEventListener("wheel", handleWheel, { capture: true });
    };
  }, []);
}

export function PageShell({
  className,
  children,
  onWheelCapture,
  ...props
}: React.ComponentProps<"section">) {
  const handleWheelCapture = useDocumentWheelFallback();
  useNativeDocumentWheelFallback();

  return (
    <section
      className={cn("min-w-0 space-y-5 pb-6", className)}
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

export function PageViewportShell({
  className,
  children,
  wheelTargetRef,
  onWheelCapture,
  ...props
}: React.ComponentProps<"section"> & {
  wheelTargetRef?: WheelTargetRef;
}) {
  const containerRef = React.useRef<HTMLElement | null>(null);
  const handleWheelCapture = useWheelFallback(wheelTargetRef);
  useNativeWheelFallback(containerRef, wheelTargetRef);

  return (
    <section
      ref={containerRef}
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
