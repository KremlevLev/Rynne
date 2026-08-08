type NovaMarkProps = {
  size?: number;
  className?: string;
};

export function NovaMark({ size = 24, className }: NovaMarkProps) {
  const classes = ["nova-mark", className].filter(Boolean).join(" ");
  return (
    <img
      className={classes}
      src="/nova-icon-green.png"
      width={size}
      alt=""
      aria-hidden="true"
      draggable={false}
    />
  );
}
