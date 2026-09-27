using System;
using System.IO;
using System.Threading;
using System.Threading.Tasks;

namespace UnityLudometry.Protocol.Framing;

/// <summary>Frame size limits. A frame is a 4-byte little-endian payload length followed by the UTF-8 JSON payload.</summary>
public static class FrameLimits
{
    /// <summary>The default maximum payload size of one frame: 16 MiB.</summary>
    public const int DefaultMaxFrameBytes = 16 * 1024 * 1024;

    /// <summary>Size of the length prefix.</summary>
    public const int HeaderBytes = 4;
}

/// <summary>
/// Reads frames from a stream. Handles partial reads. A frame that is empty, truncated or larger than the limit
/// throws <see cref="ProtocolException"/> (<c>INVALID_FRAME</c> / <c>FRAME_TOO_LARGE</c>); after that the stream is
/// out of sync and the connection must be closed. Not thread-safe.
/// </summary>
public sealed class FrameReader
{
    private readonly Stream _stream;
    private readonly byte[] _header = new byte[FrameLimits.HeaderBytes];

    /// <summary>Creates a reader.</summary>
    public FrameReader(Stream stream, int maxFrameBytes = FrameLimits.DefaultMaxFrameBytes)
    {
        _stream = stream ?? throw new ArgumentNullException(nameof(stream));
        if (maxFrameBytes <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maxFrameBytes));
        }

        MaxFrameBytes = maxFrameBytes;
    }

    /// <summary>The largest accepted payload.</summary>
    public int MaxFrameBytes { get; }

    /// <summary>Reads the next frame's payload, or returns <c>null</c> when the stream ends cleanly between frames.</summary>
    public byte[]? ReadFrame()
    {
        var headerRead = ReadFully(_header, 0, _header.Length);
        if (headerRead == 0)
        {
            return null;
        }

        var length = ParseHeader(headerRead);
        var payload = new byte[length];
        if (ReadFully(payload, 0, length) != length)
        {
            throw Truncated();
        }

        return payload;
    }

    /// <summary>Reads the next frame's payload asynchronously, or returns <c>null</c> at a clean end of stream.</summary>
    public async Task<byte[]?> ReadFrameAsync(CancellationToken cancellationToken = default)
    {
        var headerRead = await ReadFullyAsync(_header, 0, _header.Length, cancellationToken).ConfigureAwait(false);
        if (headerRead == 0)
        {
            return null;
        }

        var length = ParseHeader(headerRead);
        var payload = new byte[length];
        if (await ReadFullyAsync(payload, 0, length, cancellationToken).ConfigureAwait(false) != length)
        {
            throw Truncated();
        }

        return payload;
    }

    private int ParseHeader(int headerRead)
    {
        if (headerRead != FrameLimits.HeaderBytes)
        {
            throw Truncated();
        }

        var length = (uint)(_header[0] | (_header[1] << 8) | (_header[2] << 16) | (_header[3] << 24));
        if (length == 0)
        {
            throw new ProtocolException(ErrorCodes.InvalidFrame, "Empty frame.");
        }

        if (length > (uint)MaxFrameBytes)
        {
            throw new ProtocolException(ErrorCodes.FrameTooLarge, $"Frame of {length} bytes exceeds the limit of {MaxFrameBytes} bytes.");
        }

        return (int)length;
    }

    private static ProtocolException Truncated() => new(ErrorCodes.InvalidFrame, "The stream ended in the middle of a frame.");

    private int ReadFully(byte[] buffer, int offset, int count)
    {
        var total = 0;
        while (total < count)
        {
            var read = _stream.Read(buffer, offset + total, count - total);
            if (read == 0)
            {
                break;
            }

            total += read;
        }

        return total;
    }

    private async Task<int> ReadFullyAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken)
    {
        var total = 0;
        while (total < count)
        {
            var read = await _stream.ReadAsync(buffer, offset + total, count - total, cancellationToken).ConfigureAwait(false);
            if (read == 0)
            {
                break;
            }

            total += read;
        }

        return total;
    }
}

/// <summary>
/// Writes frames to a stream. Refuses payloads above the limit, so a peer never receives a frame it must reject.
/// Not thread-safe: use one writer per connection and serialize calls (e.g. with a send queue).
/// </summary>
public sealed class FrameWriter
{
    private readonly Stream _stream;

    /// <summary>Creates a writer.</summary>
    public FrameWriter(Stream stream, int maxFrameBytes = FrameLimits.DefaultMaxFrameBytes)
    {
        _stream = stream ?? throw new ArgumentNullException(nameof(stream));
        if (maxFrameBytes <= 0)
        {
            throw new ArgumentOutOfRangeException(nameof(maxFrameBytes));
        }

        MaxFrameBytes = maxFrameBytes;
    }

    /// <summary>The largest payload this writer sends.</summary>
    public int MaxFrameBytes { get; }

    /// <summary>Writes one frame and flushes.</summary>
    public void WriteFrame(byte[] payload) => WriteFrame(payload, 0, payload.Length);

    /// <summary>Writes one frame from a slice of a buffer and flushes.</summary>
    public void WriteFrame(byte[] payload, int offset, int count)
    {
        var header = Header(payload, offset, count);
        _stream.Write(header, 0, header.Length);
        _stream.Write(payload, offset, count);
        _stream.Flush();
    }

    /// <summary>Writes one frame asynchronously and flushes.</summary>
    public Task WriteFrameAsync(byte[] payload, CancellationToken cancellationToken = default) =>
        WriteFrameAsync(payload, 0, payload.Length, cancellationToken);

    /// <summary>Writes one frame from a slice of a buffer asynchronously and flushes.</summary>
    public async Task WriteFrameAsync(byte[] payload, int offset, int count, CancellationToken cancellationToken = default)
    {
        var header = Header(payload, offset, count);
        await _stream.WriteAsync(header, 0, header.Length, cancellationToken).ConfigureAwait(false);
        await _stream.WriteAsync(payload, offset, count, cancellationToken).ConfigureAwait(false);
        await _stream.FlushAsync(cancellationToken).ConfigureAwait(false);
    }

    private byte[] Header(byte[] payload, int offset, int count)
    {
        if (payload is null)
        {
            throw new ArgumentNullException(nameof(payload));
        }

        if (offset < 0 || count < 0 || offset + count > payload.Length)
        {
            throw new ArgumentOutOfRangeException(nameof(count));
        }

        if (count == 0)
        {
            throw new ProtocolException(ErrorCodes.InvalidFrame, "Empty frame.");
        }

        if (count > MaxFrameBytes)
        {
            throw new ProtocolException(ErrorCodes.FrameTooLarge, $"Frame of {count} bytes exceeds the limit of {MaxFrameBytes} bytes.");
        }

        return new[] { (byte)count, (byte)(count >> 8), (byte)(count >> 16), (byte)(count >> 24) };
    }
}
