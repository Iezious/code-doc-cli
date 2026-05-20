using System;
using System.Collections.Generic;
using static System.Math;
using P = System.IO.Path;

Console.WriteLine("hello");

namespace MyCorp.Widgets
{
    public class Frobnicator
    {
        public Frobnicator() { }

        public int Bar(int x)
        {
            int Local(int y) => y * 2;
            return Local(x);
        }
    }

    public struct Point2
    {
        public int X;
    }

    public record Rec(int X, string Name);

    public interface IBaz
    {
        void Quux();
    }

    public enum Color
    {
        Red,
        Green,
    }
}
