import type { ButtonHTMLAttributes, ReactNode } from "react";

export type ButtonVariant = "primary" | "secondary" | "outline" | "ghost" | "danger" | "success" | "warning" | "link";
export type ButtonSize = "small" | "medium" | "large";
export interface ButtonProps extends Omit<ButtonHTMLAttributes<HTMLButtonElement>, "className"> {
  variant?: ButtonVariant;
  size?: ButtonSize;
  icon?: ReactNode;
  className?: string;
}

/** Standard Velora action button. Use semantic variants rather than one-off colours. */
export default function Button({ variant = "secondary", size = "medium", icon, className = "", children, type = "button", ...props }: ButtonProps) {
  return <button type={type} className={`vbtn vbtn-${variant} vbtn-${size}${className ? ` ${className}` : ""}`} {...props}>
    {icon && <span className="vbtn-icon" aria-hidden="true">{icon}</span>}
    {children}
  </button>;
}
