namespace MyCorp

open System
open System.IO

module Geometry =

    type Point = { X: int; Y: int }

    type Color =
        | Red
        | Green of int
        | Blue of name: string

    let origin = { X = 0; Y = 0 }

    let rec distance (a: Point) (b: Point) : float =
        sqrt (float ((a.X - b.X) * (a.X - b.X) + (a.Y - b.Y) * (a.Y - b.Y)))

    type FooBuilder() =
        member _.Return(x) = [x]

    let foo = FooBuilder()
