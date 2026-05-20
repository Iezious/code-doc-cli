integer counter = 0;
string name = "widget";

integer add(integer x, integer y)
{
    return x + y;
}

default
{
    state_entry()
    {
        llSay(0, "ready");
        llListen(42, "", NULL_KEY, "");
        osSetSpeed(1.0);
    }

    touch_start(integer n)
    {
        llMessageLinked(LINK_THIS, 1, "touched", "");
        llHTTPRequest("https://example.invalid/x", [], "");
        llEmail("dest@example.invalid", "hello", "body");
    }
}

state idle
{
    state_entry()
    {
        llSay(0, "idle");
    }
}
