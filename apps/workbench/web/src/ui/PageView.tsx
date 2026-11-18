// One page of a document with boxes drawn over it.
//
// This file and PageView.css stand alone: they import nothing else from the workbench. Box
// coordinates are in the page's own units, the same units as `width` and `height`, with the
// origin at the top left.
import { useState } from "react";

import "./PageView.css";

export interface PageBox {
  /** Returned by the events. Boxes that share an id are one thing drawn in several places. */
  id: string;
  x0: number;
  y0: number;
  x1: number;
  y1: number;
  /** Any CSS colour. */
  color: string;
  /** Shown while the pointer is over the box. */
  label: string;
  /** How the box is drawn. "outline" is the default. */
  look?: "outline" | "wash" | "strong";
}

export interface PageViewProps {
  /** The page image. It is stretched over the whole page. */
  src: string;
  /** The page's size, in the units the boxes use. */
  width: number;
  height: number;
  boxes: readonly PageBox[];
  /** Read out in place of the image. */
  alt: string;
  onBoxEnter?: (id: string) => void;
  onBoxLeave?: (id: string) => void;
  onBoxClick?: (id: string) => void;
}

export function PageView(props: PageViewProps) {
  const { src, width, height, boxes, alt, onBoxEnter, onBoxLeave, onBoxClick } = props;
  const [over, setOver] = useState<PageBox | null>(null);
  const [loaded, setLoaded] = useState(false);
  // One page unit in pixels is not known here, so strokes do not scale with the page.
  return (
    <div className="pageview" style={{ aspectRatio: `${width} / ${height}` }}>
      <img
        className="pageview-image"
        src={src}
        alt={alt}
        draggable={false}
        decoding="async"
        data-loaded={loaded}
        onLoad={() => setLoaded(true)}
      />
      <svg
        className="pageview-boxes"
        viewBox={`0 0 ${width} ${height}`}
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        {boxes.map((box, index) => (
          <rect
            key={`${box.id}:${index}`}
            className="pageview-box"
            data-look={box.look ?? "outline"}
            data-box={box.id}
            data-clickable={onBoxClick ? true : undefined}
            x={box.x0}
            y={box.y0}
            width={Math.max(box.x1 - box.x0, 0)}
            height={Math.max(box.y1 - box.y0, 0)}
            style={{ color: box.color }}
            onPointerEnter={() => {
              setOver(box);
              onBoxEnter?.(box.id);
            }}
            onPointerLeave={() => {
              setOver((current) => (current === box ? null : current));
              onBoxLeave?.(box.id);
            }}
            onClick={onBoxClick ? () => onBoxClick(box.id) : undefined}
          />
        ))}
      </svg>
      {over && over.label !== "" ? (
        <div
          className="pageview-label"
          role="tooltip"
          data-below={over.y0 / height < 0.06}
          style={{
            left: `${(Math.min(over.x0, width * 0.7) / width) * 100}%`,
            top: `${((over.y0 / height < 0.06 ? over.y1 : over.y0) / height) * 100}%`,
          }}
        >
          {over.label}
        </div>
      ) : null}
    </div>
  );
}
