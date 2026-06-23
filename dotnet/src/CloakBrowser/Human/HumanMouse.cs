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
    private static double EaseInOut(double t)
    {
        if (t < 0.5)
            return 4 * t * t * t;
        return 1 - Math.Pow(-2 * t + 2, 3) / 2;
    }

    /// <summary>Cubic Bezier interpolation between four control points.</summary>
    private static Point Bezier(Point p0, Point p1, Point p2, Point p3, double t)
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
    private static (Point, Point) RandomControlPoints(Point start, Point end)
    {
        double dx = end.X - start.X;
        double dy = end.Y - start.Y;
        double dist = Math.Sqrt(dx * dx + dy * dy);
        if (dist == 0) dist = 1;
        double px = -dy / dist;
        double py = dx / dist;
        double bias1 = HumanRandom.Rand(-0.3, 0.3) * dist;
        double bias2 = HumanRandom.Rand(-0.3, 0.3) * dist;
        return (
            new Point(start.X + dx * 0.25 + px * bias1, start.Y + dy * 0.25 + py * bias1),
            new Point(start.X + dx * 0.75 + px * bias2, start.Y + dy * 0.75 + py * bias2));
    }

    /// <summary>
    /// Move the cursor from (startX, startY) to (endX, endY) along a human-like
    /// Bezier curve with wobble, burst pauses, and an optional overshoot.
    /// </summary>
    public static async Task HumanMoveAsync(
        IRawMouse raw,
        double startX, double startY,
        double endX, double endY,
        HumanConfig cfg)
    {
        double dist = Math.Sqrt((endX - startX) * (endX - startX) + (endY - startY) * (endY - startY));
        if (dist < 1)
            return;

        int steps = (int)Math.Max(cfg.MouseMinSteps,
            Math.Min(cfg.MouseMaxSteps, Math.Round(dist / cfg.MouseStepsDivisor)));
        var start = new Point(startX, startY);
        var end = new Point(endX, endY);
        var (cp1, cp2) = RandomControlPoints(start, end);

        int burstCounter = 0;
        int burstSize = HumanRandom.RandIntRange(cfg.MouseBurstSize);

        for (int i = 0; i <= steps; i++)
        {
            double progress = (double)i / steps;
            double easedT = EaseInOut(progress);
            var pt = Bezier(start, cp1, cp2, end, easedT);

            double wobbleAmp = Math.Sin(Math.PI * progress) * cfg.MouseWobbleMax;
            double wx = pt.X + (HumanRandom.NextDouble() - 0.5) * 2 * wobbleAmp;
            double wy = pt.Y + (HumanRandom.NextDouble() - 0.5) * 2 * wobbleAmp;

            await raw.MoveAsync(Math.Round(wx), Math.Round(wy)).ConfigureAwait(false);

            burstCounter++;
            if (burstCounter >= burstSize && i < steps)
            {
                await HumanRandom.SleepMsAsync(HumanRandom.RandRange(cfg.MouseBurstPause)).ConfigureAwait(false);
                burstCounter = 0;
            }
        }

        if (HumanRandom.NextDouble() < cfg.MouseOvershootChance)
        {
            double overshootDist = HumanRandom.RandRange(cfg.MouseOvershootPx);
            double angle = Math.Atan2(endY - startY, endX - startX);
            await raw.MoveAsync(
                Math.Round(endX + Math.Cos(angle) * overshootDist),
                Math.Round(endY + Math.Sin(angle) * overshootDist)).ConfigureAwait(false);
            await HumanRandom.SleepMsAsync(HumanRandom.Rand(30, 70)).ConfigureAwait(false);
            await raw.MoveAsync(
                Math.Round(endX + (HumanRandom.NextDouble() - 0.5) * 4),
                Math.Round(endY + (HumanRandom.NextDouble() - 0.5) * 4)).ConfigureAwait(false);
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
