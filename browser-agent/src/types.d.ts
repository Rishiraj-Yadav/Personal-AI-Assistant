// Optional desktop automation dependencies — not installed by default
declare module "screenshot-desktop" {
  function screenshot(options?: { filename?: string }): Promise<Buffer>;
  export default screenshot;
}

declare module "@nut-tree/nut-js" {
  export class Point {
    constructor(x: number, y: number);
  }
  export const mouse: {
    setPosition(point: Point): Promise<void>;
    click(button: any): Promise<void>;
  };
  export const keyboard: {
    type(text: string): Promise<void>;
    pressKey(key: any): Promise<void>;
    releaseKey(key: any): Promise<void>;
  };
  export const Button: {
    LEFT: any;
    RIGHT: any;
    MIDDLE: any;
  };
  export const Key: Record<string, any>;
}
