using UnityLudometry.Protocol.Framing;

namespace UnityLudometry.Protocol.Tests;

public sealed class FramingTests
{
    [Fact]
    public void Frames_round_trip_and_end_cleanly()
    {
        using var stream = new MemoryStream();
        var writer = new FrameWriter(stream);
        writer.WriteFrame(new byte[] { 1, 2, 3 });
        writer.WriteFrame(new byte[] { 4 });
        stream.Position = 0;

        var reader = new FrameReader(stream);
        Assert.Equal(new byte[] { 1, 2, 3 }, reader.ReadFrame());
        Assert.Equal(new byte[] { 4 }, reader.ReadFrame());
        Assert.Null(reader.ReadFrame());
    }

    [Fact]
    public void The_length_prefix_is_little_endian()
    {
        using var stream = new MemoryStream();
        new FrameWriter(stream).WriteFrame(new byte[0x0102]);
        var bytes = stream.ToArray();
        Assert.Equal(new byte[] { 0x02, 0x01, 0x00, 0x00 }, bytes[..4]);
        Assert.Equal(4 + 0x0102, bytes.Length);
    }

    [Fact]
    public async Task Handles_partial_reads()
    {
        using var inner = new MemoryStream();
        var writer = new FrameWriter(inner);
        writer.WriteFrame(new byte[] { 9, 8, 7, 6, 5 });
        writer.WriteFrame(new byte[] { 1 });
        inner.Position = 0;

        var reader = new FrameReader(new TrickleStream(inner));
        Assert.Equal(new byte[] { 9, 8, 7, 6, 5 }, await reader.ReadFrameAsync(TestContext.Current.CancellationToken));
        Assert.Equal(new byte[] { 1 }, reader.ReadFrame());
        Assert.Null(await reader.ReadFrameAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public async Task Carries_a_16_MiB_payload()
    {
        var payload = new byte[FrameLimits.DefaultMaxFrameBytes];
        new Random(42).NextBytes(payload);
        using var stream = new MemoryStream();
        await new FrameWriter(stream).WriteFrameAsync(payload, TestContext.Current.CancellationToken);
        stream.Position = 0;
        Assert.Equal(payload, await new FrameReader(stream).ReadFrameAsync(TestContext.Current.CancellationToken));
    }

    [Fact]
    public void Rejects_oversized_frames_on_both_sides()
    {
        using var stream = new MemoryStream();
        var e = Assert.Throws<ProtocolException>(() => new FrameWriter(stream, maxFrameBytes: 4).WriteFrame(new byte[5]));
        Assert.Equal(ErrorCodes.FrameTooLarge, e.Code);
        Assert.Equal(0, stream.Length);

        new FrameWriter(stream).WriteFrame(new byte[5]);
        stream.Position = 0;
        e = Assert.Throws<ProtocolException>(() => new FrameReader(stream, maxFrameBytes: 4).ReadFrame());
        Assert.Equal(ErrorCodes.FrameTooLarge, e.Code);
    }

    [Fact]
    public void Rejects_a_length_above_int_range_without_allocating()
    {
        using var stream = new MemoryStream(new byte[] { 0xFF, 0xFF, 0xFF, 0xFF });
        var e = Assert.Throws<ProtocolException>(() => new FrameReader(stream).ReadFrame());
        Assert.Equal(ErrorCodes.FrameTooLarge, e.Code);
    }

    [Theory]
    [InlineData(new byte[] { 0, 0, 0, 0 })]
    [InlineData(new byte[] { 1, 0 })]
    [InlineData(new byte[] { 3, 0, 0, 0, 1 })]
    public void Rejects_empty_and_truncated_frames(byte[] bytes)
    {
        using var stream = new MemoryStream(bytes);
        var e = Assert.Throws<ProtocolException>(() => new FrameReader(stream).ReadFrame());
        Assert.Equal(ErrorCodes.InvalidFrame, e.Code);
    }

    [Fact]
    public void Refuses_to_write_an_empty_frame()
    {
        using var stream = new MemoryStream();
        var e = Assert.Throws<ProtocolException>(() => new FrameWriter(stream).WriteFrame(Array.Empty<byte>()));
        Assert.Equal(ErrorCodes.InvalidFrame, e.Code);
    }

    /// <summary>Returns at most one byte per read, like a slow pipe.</summary>
    private sealed class TrickleStream(Stream inner) : Stream
    {
        public override bool CanRead => true;

        public override bool CanSeek => false;

        public override bool CanWrite => false;

        public override long Length => throw new NotSupportedException();

        public override long Position
        {
            get => throw new NotSupportedException();
            set => throw new NotSupportedException();
        }

        public override int Read(byte[] buffer, int offset, int count) => inner.Read(buffer, offset, Math.Min(1, count));

        public override Task<int> ReadAsync(byte[] buffer, int offset, int count, CancellationToken cancellationToken) =>
            Task.FromResult(Read(buffer, offset, count));

        public override void Flush()
        {
        }

        public override long Seek(long offset, SeekOrigin origin) => throw new NotSupportedException();

        public override void SetLength(long value) => throw new NotSupportedException();

        public override void Write(byte[] buffer, int offset, int count) => throw new NotSupportedException();
    }
}
