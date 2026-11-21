using System;
using System.Collections;
using System.Collections.Generic;
using System.Reflection;
using Godot.Bridge;
using Godot.NativeInterop;

namespace LeanClr
{
    public static partial class Bootstrap
    {
        public static void Initialize() { }
        public static void Tick(float delta) { }
        public static void Shutdown() { }
        public static unsafe void ReportException(Exception exception, char* buffer, int capacity)
        {
            string message = exception.GetType().FullName + ": " + exception.Message + "\n" + exception.StackTrace;
            int count = Math.Min(message.Length, capacity - 1);
            for (int i = 0; i < count; ++i) buffer[i] = message[i];
            buffer[count] = '\0';
        }

        public static void Attach(IntPtr functions, int size)
        {
            try
            {
                Console.WriteLine("LEANCLR_ATTACH native-functions");
                NativeFuncs.Initialize(functions, size);
                AlcReloadCfg.Configure(false);
                Console.WriteLine("LEANCLR_ATTACH script-registration");
                RegisterScripts();
                LogScriptBridgeState();
                Console.WriteLine("LEANCLR_ATTACH ready");
            }
            catch (Exception exception)
            {
                Console.WriteLine("LEANCLR_ATTACH_ERROR " + exception.GetType().FullName + ": " + exception.Message);
                Console.WriteLine(exception.StackTrace);
                throw;
            }
        }

        private static void LogScriptBridgeState()
        {
            try
            {
                const BindingFlags Flags = BindingFlags.NonPublic | BindingFlags.Static;
                object map = typeof(ScriptManagerBridge).GetField("_pathTypeBiMap", Flags)?.GetValue(null);
                object pathsValue = map?.GetType().GetProperty("Paths")?.GetValue(map);
                var paths = new List<string>();
                if (pathsValue is IEnumerable enumerable)
                {
                    foreach (object path in enumerable)
                        paths.Add(path?.ToString() ?? "");
                }
                Console.WriteLine("LEANCLR_BRIDGE_PATHS " + string.Join("|", paths));

                object factories = typeof(ScriptManagerBridge).GetField("_publishedFactories", Flags)?.GetValue(null);
                Console.WriteLine("LEANCLR_BRIDGE_FACTORIES " + ((factories as IDictionary)?.Count ?? -1));
            }
            catch (Exception exception)
            {
                Console.WriteLine("LEANCLR_BRIDGE_STATE_ERROR " + exception.GetType().FullName + ": " + exception.Message);
            }
        }
        static partial void RegisterScripts();
    }
}
