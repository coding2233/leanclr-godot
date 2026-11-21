"""Build the project-independent publication GodotSharp, calli catalog and analyzers."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil

from linux_common import ROOT, dotnet_build, find_first, read_json, run, sha256, write_json


def build_analyzer(project: Path, configuration: str = "Debug") -> Path:
    dotnet_build(project, configuration=configuration)
    expected = project.parent / f"bin/{configuration}/netstandard2.0/{project.stem}.dll"
    if expected.is_file():
        return expected
    candidates = sorted(project.parent.glob(f"bin/{configuration}/netstandard2.0/*.dll"))
    return find_first(candidates, f"analyzer output for {project}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--godot-source", type=Path, default=ROOT / "extern/godot")
    parser.add_argument("--editor", type=Path, default=Path("/opt/godot/Godot_v4.7.2-stable_mono_linux.x86_64"))
    parser.add_argument("--leanclr-source", type=Path, default=ROOT / "extern/leanclr")
    parser.add_argument("--out", type=Path, default=ROOT / "build/m1")
    parser.add_argument("--bcl", type=Path, required=True,
                        help="10.0.8 managed BCL directory (win-x64 runtime pack lib/net10.0)")
    args = parser.parse_args()

    godot = args.godot_source.resolve()
    editor = args.editor.resolve()
    leanclr = args.leanclr_source.resolve()
    out = args.out.resolve()
    bcl = args.bcl.resolve()
    if not editor.is_file():
        raise FileNotFoundError(f"official Godot editor is missing: {editor}")
    if not (leanclr / "src/runtime/CMakeLists.txt").is_file():
        raise FileNotFoundError(f"LeanCLR submodule is not initialized: {leanclr}")
    if not (bcl / "System.Private.CoreLib.dll").is_file():
        raise FileNotFoundError(f"10.0.8 BCL is missing: {bcl}")

    out.mkdir(parents=True, exist_ok=True)
    glue = out / "glue"
    generated = glue / "GodotSharp/GodotSharp/Generated"
    if not generated.is_dir():
        run([editor, "--headless", "--editor", "--generate-mono-glue", glue],
            log=out / "generate-mono-glue.log")
    if not generated.is_dir():
        raise RuntimeError("Godot did not generate mono glue")

    source = godot / "modules/mono/glue/GodotSharp"
    internal_project = source / "Godot.SourceGenerators.Internal/Godot.SourceGenerators.Internal.csproj"
    public_project = godot / "modules/mono/editor/Godot.NET.Sdk/Godot.SourceGenerators/Godot.SourceGenerators.csproj"
    internal_analyzer = build_analyzer(internal_project)
    public_analyzer = build_analyzer(public_project)

    stage = out / "managed/GodotSharp"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)
    for name in ["Core", "Properties"]:
        shutil.copytree(source / "GodotSharp" / name, stage / name)
    for name in ["GlobalUsings.cs", "Compat.cs"]:
        shutil.copyfile(source / "GodotSharp" / name, stage / name)
    shutil.copytree(generated, stage / "Generated")

    (stage / "Core/Bridge/ScriptManagerBridge.publication.cs").write_text('''using System;
using System.Collections.Generic;
namespace Godot.Bridge {
 public static partial class ScriptManagerBridge {
  private static readonly Dictionary<Type, Func<GodotObject>> _publishedFactories = new();
  public static void RegisterPublishedScript(Type type, string path, Func<GodotObject> factory) {
   _pathTypeBiMap.Add(path, type);
   _publishedFactories.Add(type, factory);
  }
 }
 internal static class PublicationConstruction {
  [ThreadStatic] private static Type _expectedType;
  [ThreadStatic] private static IntPtr _native;
  internal static IntPtr Take(Type actual) {
   if (actual != _expectedType) return IntPtr.Zero;
   IntPtr result = _native;
   _expectedType = null;
   _native = IntPtr.Zero;
   return result;
  }
  internal static GodotObject Construct(Type type, IntPtr native, Func<GodotObject> factory) {
   Type previousType = _expectedType;
   IntPtr previousNative = _native;
   _expectedType = type;
   _native = native;
   try {
    GodotObject instance = factory();
    if (instance.NativePtr != native) throw new InvalidOperationException("Native script constructor association failed.");
    return instance;
   } finally { _expectedType = previousType; _native = previousNative; }
  }
 }
}
''', encoding="utf-8")

    script_bridge = stage / "Core/Bridge/ScriptManagerBridge.cs"
    bridge_text = script_bridge.read_text(encoding="utf-8")
    method_start = bridge_text.index("internal static unsafe godot_bool CreateManagedForGodotObjectScriptInstance")
    body_start = bridge_text.index("                // Performance is not critical here", method_start)
    body_end = bridge_text.index("                return godot_bool.True;", body_start)
    bridge_text = bridge_text[:body_start] + '''                if (argCount != 0)
                    throw new NotSupportedException("LeanCLR publication factories support parameterless script constructors only.");
                Type scriptType = _scriptTypeBiMap.GetScriptType(scriptPtr);
                PublicationConstruction.Construct(scriptType, godotObject, _publishedFactories[scriptType]);
''' + bridge_text[body_end:]
    bridge_text = bridge_text.replace(
        "string scriptPathStr = Marshaling.ConvertStringToManaged(*scriptPath);",
        'string scriptPathStr = Marshaling.ConvertStringToManaged(*scriptPath);\n            Console.WriteLine("LEANCLR_BRIDGE_LOOKUP " + scriptPathStr);')
    bridge_text = bridge_text.replace(
        "NativeFuncs.godotsharp_internal_new_csharp_script(outScript);\n                return;",
        'Console.WriteLine("LEANCLR_BRIDGE_MISS " + scriptPathStr);\n                NativeFuncs.godotsharp_internal_new_csharp_script(outScript);\n                return;')
    bridge_text = bridge_text.replace(
        "GetOrCreateScriptBridgeForType(scriptType, outScript);",
        'Console.WriteLine("LEANCLR_BRIDGE_FOUND " + scriptType.FullName);\n            GetOrCreateScriptBridgeForType(scriptType, outScript);')
    bridge_text = bridge_text.replace(
        "NativeFuncs.godotsharp_internal_new_csharp_script(outScript);\n                IntPtr scriptPtr = outScript->Reference;",
        'Console.WriteLine("LEANCLR_BRIDGE_CREATE " + scriptType.FullName);\n                NativeFuncs.godotsharp_internal_new_csharp_script(outScript);\n                Console.WriteLine("LEANCLR_BRIDGE_CREATED " + outScript->Reference);\n                IntPtr scriptPtr = outScript->Reference;')
    bridge_text = bridge_text.replace(
        "NativeFuncs.godotsharp_internal_reload_registered_script(outScript->Reference);",
        'Console.WriteLine("LEANCLR_BRIDGE_RELOAD " + scriptType.FullName);\n            NativeFuncs.godotsharp_internal_reload_registered_script(outScript->Reference);\n            Console.WriteLine("LEANCLR_BRIDGE_RELOADED");')
    for lock_call in (
        "ReadWriteLock.EnterUpgradeableReadLock();",
        "ReadWriteLock.ExitUpgradeableReadLock();",
        "ReadWriteLock.EnterWriteLock();",
        "ReadWriteLock.ExitWriteLock();",
    ):
        bridge_text = bridge_text.replace("_scriptTypeBiMap." + lock_call, "")
    script_bridge.write_text(bridge_text, encoding="utf-8")

    disposables = stage / "Core/DisposablesTracker.cs"
    disposables.write_text(disposables.read_text(encoding="utf-8").replace(
        "                OnGodotShuttingDownImpl();",
        "                GC.Collect();\n                GC.WaitForPendingFinalizers();\n                OnGodotShuttingDownImpl();"), encoding="utf-8")

    native = stage / "Core/NativeInterop/NativeFuncs.cs"
    native.write_text(native.read_text(encoding="utf-8").replace(
        "partial delegate* unmanaged<godot_bool, IntPtr> godotsharp_get_class_constructor",
        "partial IntPtr godotsharp_get_class_constructor"), encoding="utf-8")

    obj = stage / "Core/GodotObject.base.cs"
    obj.write_text(obj.read_text(encoding="utf-8").replace(
        "var nativeConstructor = NativeFuncs.godotsharp_get_class_constructor(typeSelf);",
        "var nativeConstructor = (delegate* unmanaged<godot_bool, IntPtr>)(void*)NativeFuncs.godotsharp_get_class_constructor(typeSelf);"
    ).replace("_memoryOwn = memoryOwn;",
              "_memoryOwn = memoryOwn;\n            NativePtr = PublicationConstruction.Take(GetType());"),
        encoding="utf-8")

    (stage / "GodotSharp.csproj").write_text(f'''<Project Sdk="Microsoft.NET.Sdk">
  <PropertyGroup>
    <TargetFramework>net10.0</TargetFramework><AssemblyName>GodotSharp</AssemblyName>
    <AssemblyVersion>4.7.2.0</AssemblyVersion><AllowUnsafeBlocks>true</AllowUnsafeBlocks>
    <DefineConstants>GODOT</DefineConstants><EnableDefaultCompileItems>false</EnableDefaultCompileItems>
    <NoWarn>1591;8632</NoWarn><GenerateDocumentationFile>false</GenerateDocumentationFile>
  </PropertyGroup>
  <ItemGroup>
    <Compile Include="Core/**/*.cs" /><Compile Include="Generated/**/*.cs" />
    <Compile Include="Properties/**/*.cs" /><Compile Include="GlobalUsings.cs" /><Compile Include="Compat.cs" />
    <Analyzer Include="{internal_analyzer.as_posix()}" />
  </ItemGroup>
</Project>''', encoding="utf-8")
    dotnet_build(stage / "GodotSharp.csproj", log=out / "managed-godotsharp.log")
    godotsharp = stage / "bin/Release/net10.0/GodotSharp.dll"
    if not godotsharp.is_file():
        raise RuntimeError("publication GodotSharp.dll was not produced")

    fixture = out / "signature-fixture"
    fixture.mkdir(parents=True, exist_ok=True)
    declarations = native.read_text(encoding="utf-8")
    declarations = declarations[declarations.index("        // Custom functions"):]
    (fixture / "NativeSignatures.cs").write_text('''using System;
using Godot;
using Godot.NativeInterop;
using Godot.SourceGenerators.Internal;
namespace Godot.NativeInterop {
[GenerateUnmanagedCallbacks(typeof(UnmanagedCallbacks))]
public static unsafe partial class NativeFuncs {
private partial struct UnmanagedCallbacks { }
''' + declarations, encoding="utf-8")
    (fixture / "AdditionalSignatures.cs").write_text('''using System;
using Godot.NativeInterop;
public static unsafe class AdditionalSignatures {
 public static IntPtr Constructor(IntPtr p, godot_bool b) => ((delegate* unmanaged<godot_bool, IntPtr>)(void*)p)(b);
 public static void Properties(IntPtr p, IntPtr script, godot_string* name, void* data, int count) => ((delegate* unmanaged<IntPtr, godot_string*, void*, int, void>)(void*)p)(script, name, data, count);
 public static void Defaults(IntPtr p, IntPtr script, void* data, int count) => ((delegate* unmanaged<IntPtr, void*, int, void>)(void*)p)(script, data, count);
}
''', encoding="utf-8")
    (fixture / "Signatures.csproj").write_text(f'''<Project Sdk="Microsoft.NET.Sdk">
 <PropertyGroup><TargetFramework>net10.0</TargetFramework><AssemblyName>GodotSharpEditor</AssemblyName><AllowUnsafeBlocks>true</AllowUnsafeBlocks><NoWarn>0436;0169</NoWarn></PropertyGroup>
 <ItemGroup><Reference Include="GodotSharp"><HintPath>{godotsharp.as_posix()}</HintPath></Reference>
 <Analyzer Include="{internal_analyzer.as_posix()}" /></ItemGroup>
</Project>''', encoding="utf-8")
    dotnet_build(fixture / "Signatures.csproj", log=out / "signature-fixture.log")

    leanaot_project = leanclr / "src/leanaot/LeanAOT/LeanAOT.csproj"
    dotnet_build(leanaot_project, log=out / "leanaot-build.log")
    leanaot_candidates = [
        leanclr / "out/dotnet/LeanAOT/Release/net8.0/LeanAOT.dll",
        leanclr / "src/leanaot/LeanAOT/bin/Release/net8.0/LeanAOT.dll",
    ]
    if not any(path.is_file() for path in leanaot_candidates):
        leanaot_candidates.extend(sorted(leanclr.rglob("LeanAOT.dll")))
    leanaot = find_first(leanaot_candidates, "LeanAOT.dll")

    calli = out / "calli"
    run(["dotnet", leanaot,
         "--leanaot-runtime-api-profile", "coreclr-net10",
         "-d", fixture / "bin/Release/net10.0",
         "-d", bcl,
         "-a", "GodotSharpEditor",
         "-o", calli,
         "--calli-bridges-only"], log=out / "calli.log")
    inventory = read_json(calli / "calli_bridges.json")
    if inventory.get("bridge_count", 0) <= 0:
        raise RuntimeError("incomplete calli bridge catalog")
    if any(site.get("status") != "generated" for site in inventory.get("sites", [])):
        raise RuntimeError("calli catalog contains unresolved sites")

    managed = out / "managed"
    analyzers = managed / "analyzers"
    analyzers.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(godotsharp, managed / "GodotSharp.dll")
    shutil.copyfile(public_analyzer, analyzers / "Godot.SourceGenerators.dll")
    shutil.copyfile(internal_analyzer, analyzers / "Godot.SourceGenerators.Internal.dll")

    dependencies = read_json(ROOT / "dependencies.json")
    profile = {
        "schema": 1,
        "target": "linux",
        "abi": "x86_64",
        "pointer_bits": 64,
        "real_bits": 32,
        "godot_commit": dependencies["godot"]["commit"],
        "leanclr_commit": dependencies["leanclr"]["commit"],
        "corelib_version": dependencies["corelib"]["version"],
        "corelib_native_sha256": dependencies["corelib"]["native_sha256"],
        "godotsharp_sha256": sha256(godotsharp),
        "calli_sha256": sha256(calli / "calli_bridges.json"),
        "managed": {
            "godotsharp": "managed/GodotSharp.dll",
            "source_generator": "managed/analyzers/Godot.SourceGenerators.dll",
        },
    }
    write_json(out / "profile.json", profile)
    print("GENERIC_MANAGED_OK", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
