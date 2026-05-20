import { useState } from "react";
import type { ReactNode } from "react";
import * as fs from "fs";

export type Box<T> = { value: T };
export interface Container<T> {
    items: T[];
}
export enum Color { Red, Green, Blue }

namespace Geometry {
    export class Point { constructor(public x: number, public y: number) {} }
    export function distance(a: Point, b: Point): number { return 0; }
}

export class Widget {
    items: Color[] = [];
    render(): ReactNode { return null; }
}

export default function () { return new Widget(); }
