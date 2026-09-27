using System.Text;
using UnityLudometry.Protocol.Json;

namespace UnityLudometry.Protocol.Tests;

/// <summary>Property-style tests: random JSON trees survive write → read → write unchanged.</summary>
public sealed class RandomTreeTests
{
    [Theory]
    [InlineData(1)]
    [InlineData(2)]
    [InlineData(3)]
    [InlineData(4)]
    [InlineData(5)]
    public void Random_trees_round_trip(int seed)
    {
        var random = new Random(seed);
        for (var i = 0; i < 200; i++)
        {
            var tree = RandomValue(random, depth: 0);
            var bytes = tree.ToUtf8Bytes();
            var parsed = JsonValue.Parse(bytes);
            Assert.True(JsonValue.DeepEquals(tree, parsed), $"seed {seed}, tree {i}: {Encoding.UTF8.GetString(bytes)}");
            Assert.Equal(bytes, parsed.ToUtf8Bytes());
        }
    }

    private static JsonValue RandomValue(Random random, int depth)
    {
        var kind = random.Next(depth >= 6 ? 4 : 6);
        switch (kind)
        {
            case 0:
                return random.Next(3) switch { 0 => JsonNull.Instance, 1 => JsonBoolean.True, _ => JsonBoolean.False };
            case 1:
                return random.Next(4) switch
                {
                    0 => new JsonNumber((long)random.NextInt64(long.MinValue, long.MaxValue)),
                    1 => new JsonNumber((random.NextDouble() - 0.5) * Math.Pow(10, random.Next(-300, 300))),
                    2 => new JsonNumber((ulong)random.NextInt64() * 2),
                    _ => new JsonNumber(random.Next(-1000, 1000)),
                };
            case 2:
            case 3:
                return new JsonString(RandomString(random));
            case 4:
            {
                var array = new JsonArray();
                var count = random.Next(6);
                for (var i = 0; i < count; i++)
                {
                    array.Add(RandomValue(random, depth + 1));
                }

                return array;
            }

            default:
            {
                var obj = new JsonObject();
                var count = random.Next(6);
                for (var i = 0; i < count; i++)
                {
                    obj.Set(RandomString(random), RandomValue(random, depth + 1));
                }

                return obj;
            }
        }
    }

    private static string RandomString(Random random)
    {
        var sb = new StringBuilder();
        var length = random.Next(12);
        for (var i = 0; i < length; i++)
        {
            switch (random.Next(8))
            {
                case 0:
                    sb.Append((char)random.Next(0, 0x20)); // control characters
                    break;
                case 1:
                    sb.Append("\"\\/"[random.Next(3)]);
                    break;
                case 2:
                    sb.Append((char)random.Next(0xD800, 0xE000)); // surrogates, often unpaired
                    break;
                case 3:
                    sb.Append(char.ConvertFromUtf32(random.Next(0x10000, 0x110000)));
                    break;
                case 4:
                    sb.Append((char)random.Next(0x80, 0xD800));
                    break;
                default:
                    sb.Append((char)random.Next(0x20, 0x7F));
                    break;
            }
        }

        return sb.ToString();
    }
}
