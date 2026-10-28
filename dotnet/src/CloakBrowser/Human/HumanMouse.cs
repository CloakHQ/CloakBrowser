namespace CloakBrowser.Human;

/// <summary>A 2D point used by the mouse-movement curve math.</summary>
public readonly record struct Point(double X, double Y);

/// <summary>
/// Minimal mouse abstraction the humanize layer drives. Mirrors the Python
/// <c>RawMouse</c> Protocol. Implemented over Playwright's <c>IMouse</c>.
/// All methods are async to match .NET Playwright.
/// </summary>
public interface IRawMouse
{
    Task MoveAsync(double x, double y);
    Task DownAsync();
    Task UpAsync();
    Task WheelAsync(double deltaX, double deltaY);
}

/// <summary>
/// Human-like mouse movement and clicking.
/// Direct port of Python <c>cloakbrowser/human/mouse.py</c>.
/// Movement follows a cubic Bezier curve with perpendicular wobble, burst
/// pauses, and an optional overshoot+correction at the end.
/// </summary>
public static class HumanMouse
{
    /// <summary>Cubic ease-in-out, matching the Python implementation.</summary>
    internal static double EaseInOut(double t)
    {
        if (t < 0.5)
            return 4 * t * t * t;
        return 1 - Math.Pow(-2 * t + 2, 3) / 2;
    }

    /// <summary>Cubic Bezier interpolation between four control points.</summary>
    internal static Point Bezier(Point p0, Point p1, Point p2, Point p3, double t)
    {
        double u = 1 - t;
        double uu = u * u;
        double uuu = uu * u;
        double tt = t * t;
        double ttt = tt * t;
        return new Point(
            uuu * p0.X + 3 * uu * t * p1.X + 3 * u * tt * p2.X + ttt * p3.X,
            uuu * p0.Y + 3 * uu * t * p1.Y + 3 * u * tt * p2.Y + ttt * p3.Y);
    }

    /// <summary>Generate two random control points biased perpendicular to the path.</summary>
    internal static (Point, Point) RandomControlPoints(Point start, Point end, double curvature = 0.3)
    {
        double dx = end.X - start.X;
        double dy = end.Y - start.Y;
        double dist = Math.Sqrt(dx * dx + dy * dy);
        if (dist == 0) dist = 1;
        double px = -dy / dist;
        double py = dx / dist;
        // Both control points bend the same way more often than not: a hand
        // sweeps an arc, it rarely draws an S.
        double bias1 = HumanRandom.Rand(-curvature, curvature) * dist;
        double bias2 = HumanRandom.NextDouble() < 0.8
            ? bias1 * HumanRandom.Rand(0.2, 1.2)
            : HumanRandom.Rand(-curvature, curvature) * dist;
        return (
            new Point(start.X + dx * 0.25 + px * bias1, start.Y + dy * 0.25 + py * bias1),
            new Point(start.X + dx * 0.75 + px * bias2, start.Y + dy * 0.75 + py * bias2));
    }

    // -----------------------------------------------------------------------
    // Stroke planning (shared by the humanize engine and HumanMoveAsync)
    // -----------------------------------------------------------------------
    //
    // A pointing movement is a fast main stroke whose speed peaks early, then
    // a slow approach to the target, often finished by a short corrective
    // stroke (Meyer's optimised sub-movements; Plamondon's log-normal
    // strokes). How long it takes grows with log2 of the distance (Fitts' law)
    // and varies a lot from one move to the next. A mouse reports its position
    // at a steady rate and only when it actually moved.

    /// <summary>Pointer events arrive about once per display frame.</summary>
    internal const double FrameMs = 1000.0 / 60;
    private const double PeakLo = 0.22, PeakHi = 0.38; // where the speed peaks (fraction of the stroke time)

    /// <summary>Smooth 0->1 distance curve whose speed peaks at <paramref name="peak"/> of the
    /// time (a time-warped minimum-jerk profile: fast early, long slow tail).</summary>
    private static Func<double, double> ProgressCurve(double peak)
    {
        double k = Math.Log(0.5) / Math.Log(peak); // u = t**k puts the mid point at peak
        return t =>
        {
            double u = Math.Pow(t, k);
            return u * u * u * (10 - 15 * u + 6 * u * u);
        };
    }

    /// <summary>Milliseconds for a <paramref name="dist"/> px stroke (Fitts' law, log-normal spread).</summary>
    internal static double StrokeDuration(double dist, HumanConfig cfg)
    {
        double median = cfg.MouseTimeBase + cfg.MouseTimePerBit * Math.Log2(1 + dist / 8);
        return Math.Max(FrameMs * 2, HumanRandom.RandLognormal(median, cfg.MouseTimeSpread));
    }

    /// <summary>Points of one stroke as (x, y, ms since the previous one); the last point is
    /// exactly (ex, ey). Consecutive points always differ by a pixel or more (a mouse does
    /// not report a move without movement).</summary>
    internal static List<(double X, double Y, double Dt)> PlanStroke(
        double sx, double sy, double ex, double ey, HumanConfig cfg, double? duration = null)
    {
        var output = new List<(double X, double Y, double Dt)>();
        double dist = Math.Sqrt((ex - sx) * (ex - sx) + (ey - sy) * (ey - sy));
        if (dist < 0.5) return output;
        double total = duration ?? StrokeDuration(dist, cfg);
        int n = Math.Max(1, (int)Math.Max(cfg.MouseMinSteps, Math.Min(cfg.MouseMaxSteps, Math.Round(total / FrameMs))));
        var start = new Point(sx, sy);
        var end = new Point(ex, ey);
        var (cp1, cp2) = RandomControlPoints(start, end, 0.12);
        var curve = ProgressCurve(HumanRandom.Rand(PeakLo, PeakHi));
        // Low-frequency sideways drift (a hand is not a ruler), zero at both ends.
        double ux = (ex - sx) / dist, uy = (ey - sy) / dist;
        double amp = Math.Min(cfg.MouseWobbleMax, dist * 0.02) * HumanRandom.Rand(-1, 1);
        double waves = HumanRandom.Rand(0.5, 1.5), phase = HumanRandom.Rand(0, Math.PI);
        double lx = sx, ly = sy, tPrev = 0;
        for (int i = 1; i <= n; i++)
        {
            // Frame timing jitters a little; the final event lands on the target.
            double t = Math.Min(1, (i + (i < n ? HumanRandom.Rand(-0.2, 0.2) : 0)) / n);
            double x, y;
            if (i == n)
            {
                x = ex; y = ey;
                if (Math.Abs(x - lx) < 1 && Math.Abs(y - ly) < 1)
                {
                    if (output.Count == 0) break; // already there (sub-pixel move): nothing to report
                    // The last frame already got there: land exactly on it instead.
                    var last = output[^1];
                    output[^1] = (x, y, last.Dt + (t - tPrev) * total);
                    break;
                }
            }
            else
            {
                var p = Bezier(start, cp1, cp2, end, curve(t));
                double w = amp * Math.Sin(Math.PI * t) * Math.Sin(phase + 2 * Math.PI * waves * t);
                x = Math.Round(p.X - uy * w);
                y = Math.Round(p.Y + ux * w);
                if (Math.Abs(x - lx) < 1 && Math.Abs(y - ly) < 1) continue;
            }
            output.Add((x, y, (t - tPrev) * total));
            tPrev = t; lx = x; ly = y;
        }
        return output;
    }

    /// <summary>A whole move: main stroke, and sometimes a miss near the target plus a short
    /// corrective stroke onto it.</summary>
    internal static List<(double X, double Y, double Dt)> PlanMove(
        double sx, double sy, double ex, double ey, HumanConfig cfg)
    {
        double dist = Math.Sqrt((ex - sx) * (ex - sx) + (ey - sy) * (ey - sy));
        if (dist < 0.5) return new();
        if (dist > 40 && HumanRandom.NextDouble() < cfg.MouseOvershootChance)
        {
            // Land a little past (or short of) the target, slightly off-line.
            double ang = Math.Atan2(ey - sy, ex - sx) + HumanRandom.Rand(-0.25, 0.25);
            double miss = dist * HumanRandom.Rand(0.01, 0.05) + HumanRandom.RandRange(cfg.MouseOvershootPx);
            if (HumanRandom.NextDouble() < 0.3) miss = -miss; // undershoot
            double mx = Math.Round(ex + Math.Cos(ang) * miss), my = Math.Round(ey + Math.Sin(ang) * miss);
            var pts = PlanStroke(sx, sy, mx, my, cfg);
            double corr = Math.Sqrt((ex - mx) * (ex - mx) + (ey - my) * (ey - my));
            double pause = HumanRandom.Rand(40, 140);
            var tail = PlanStroke(mx, my, ex, ey, cfg,
                Math.Max(FrameMs * 2, HumanRandom.RandLognormal(90 + 25 * Math.Log2(1 + corr), 0.3)));
            if (tail.Count > 0) tail[0] = (tail[0].X, tail[0].Y, tail[0].Dt + pause);
            pts.AddRange(tail);
            return pts;
        }
        return PlanStroke(sx, sy, ex, ey, cfg);
    }

    /// <summary>
    /// Move the cursor from (startX, startY) to (endX, endY) the way a hand does:
    /// an early-peaking main stroke timed by Fitts' law, sometimes a short
    /// corrective stroke, one pointer event per frame.
    /// </summary>
    public static async Task HumanMoveAsync(
        IRawMouse raw,
        double startX, double startY,
        double endX, double endY,
        HumanConfig cfg)
    {
        var sw = System.Diagnostics.Stopwatch.StartNew();
        double clock = 0;
        foreach (var (x, y, dt) in PlanMove(startX, startY, endX, endY, cfg))
        {
            clock += dt;
            await HumanRandom.SleepMsAsync(clock - sw.Elapsed.TotalMilliseconds).ConfigureAwait(false);
            await raw.MoveAsync(x, y).ConfigureAwait(false);
        }
    }

    /// <summary>
    /// Compute a randomized click point inside a bounding box. Inputs get a
    /// left-biased X and a wider Y band; buttons get a centered cluster.
    /// </summary>
    public static Point ClickTarget(BoundingBox box, bool isInput, HumanConfig cfg)
    {
        double xFrac, yFrac;
        if (isInput)
        {
            xFrac = HumanRandom.RandRange(cfg.ClickInputXRange);
            yFrac = HumanRandom.Rand(0.30, 0.70);
        }
        else
        {
            xFrac = HumanRandom.Rand(0.35, 0.65);
            yFrac = HumanRandom.Rand(0.35, 0.65);
        }
        return new Point(
            Math.Round(box.X + box.Width * xFrac),
            Math.Round(box.Y + box.Height * yFrac));
    }

    /// <summary>Perform a human-like press: aim delay, mouse down, hold, mouse up.</summary>
    public static async Task HumanClickAsync(IRawMouse raw, bool isInput, HumanConfig cfg)
    {
        double aimDelay = isInput
            ? HumanRandom.RandRange(cfg.ClickAimDelayInput)
            : HumanRandom.RandRange(cfg.ClickAimDelayButton);
        await HumanRandom.SleepMsAsync(aimDelay).ConfigureAwait(false);
        double holdTime = isInput
            ? HumanRandom.RandRange(cfg.ClickHoldInput)
            : HumanRandom.RandRange(cfg.ClickHoldButton);
        await raw.DownAsync().ConfigureAwait(false);
        await HumanRandom.SleepMsAsync(holdTime).ConfigureAwait(false);
        await raw.UpAsync().ConfigureAwait(false);
    }

    /// <summary>Drift the cursor with tiny random movements for ~<paramref name="seconds"/> seconds.</summary>
    public static async Task HumanIdleAsync(IRawMouse raw, double seconds, double cx, double cy, HumanConfig cfg)
    {
        var endTime = DateTime.UtcNow.AddSeconds(seconds);
        double x = cx, y = cy;
        while (DateTime.UtcNow < endTime)
        {
            double dx = (HumanRandom.NextDouble() - 0.5) * 2 * cfg.IdleDriftPx;
            double dy = (HumanRandom.NextDouble() - 0.5) * 2 * cfg.IdleDriftPx;
            x += dx;
            y += dy;
            await raw.MoveAsync(Math.Round(x), Math.Round(y)).ConfigureAwait(false);
            await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.IdlePauseRange)).ConfigureAwait(false);
        }
    }
}

/// <summary>
/// A bounding box (x, y, width, height) in CSS pixels - mirrors Playwright's
/// <c>BoundingBox</c> but kept independent so the math helpers don't depend on
/// the Playwright type directly.
/// </summary>
public readonly record struct BoundingBox(double X, double Y, double Width, double Height);
