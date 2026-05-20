import { useState } from "react";
import * as fs from "fs";
import "./side-effect";
const path = require("path");

console.log("module-scope side effect");

export function namedExport() {
    return 1;
}

const arrowAtModuleScope = (x) => x + 1;

export class Widget {
    constructor() {}
    method() { return arrowAtModuleScope(1); }
}

export default function () {
    return new Widget();
}
