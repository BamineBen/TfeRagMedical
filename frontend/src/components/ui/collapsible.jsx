import * as React from "react"
import { cn } from "@/lib/utils"

const Collapsible = React.forwardRef(({ open, onOpenChange, className, children, ...props }, ref) => {
    return (
        <div
            ref={ref}
            className={cn("", className)}
            {...props}
        >
            {React.Children.map(children, child => {
                if (React.isValidElement(child)) {
                    return React.cloneElement(child, { open, onOpenChange });
                }
                return child;
            })}
        </div>
    )
})

const CollapsibleTrigger = React.forwardRef(({ asChild, open, onOpenChange, children, onClick, ...props }, ref) => {
    const Comp = asChild ? React.Slot : "button"
    // If asChild is technically not supported without @radix-ui/react-slot, we just render children with onClick
    // Simplified: assume the child is a button, attach onClick
    const child = React.Children.only(children);
    return React.cloneElement(child, {
        onClick: (e) => {
            if (onClick) onClick(e);
            if (child.props.onClick) child.props.onClick(e);
            onOpenChange(!open);
        },
        "aria-expanded": open,
        ref
    });
})

const CollapsibleContent = React.forwardRef(({ open, className, children, ...props }, ref) => {
    if (!open) return null;
    return (
        <div
            ref={ref}
            className={cn("overflow-hidden", className)}
            {...props}
        >
            {children}
        </div>
    )
})

export { Collapsible, CollapsibleTrigger, CollapsibleContent }
