using System;
using System.Collections.Generic;
using System.Globalization;
using System.IO;
using System.Runtime.InteropServices;
using System.Text;

class Vst2Bridge {
    const int Magic = 0x56737450, EffOpen = 0, EffClose = 1, EffGetLabel = 6, EffGetDisplay = 7,
        EffGetName = 8, EffSetRate = 10, EffSetBlock = 11, EffMains = 12, EffEffectName = 45;
    const int Replacing = 1 << 4;

    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate IntPtr AudioMaster(IntPtr effect, int opcode, int index, IntPtr value, IntPtr ptr, float opt);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate IntPtr Dispatcher(IntPtr effect, int opcode, int index, IntPtr value, IntPtr ptr, float opt);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate void SetParameter(IntPtr effect, int index, float value);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate float GetParameter(IntPtr effect, int index);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate void ProcessReplacing(IntPtr effect, IntPtr inputs, IntPtr outputs, int frames);
    [UnmanagedFunctionPointer(CallingConvention.Cdecl)] delegate IntPtr Entry(AudioMaster callback);

    [StructLayout(LayoutKind.Sequential)] struct AEffect {
        public int magic; public IntPtr dispatcher, process, setParameter, getParameter;
        public int numPrograms, numParams, numInputs, numOutputs, flags;
        public IntPtr resvd1, resvd2; public int initialDelay, realQualities, offQualities;
        public float ioRatio; public IntPtr obj, user; public int uniqueID, version;
        public IntPtr processReplacing, processDoubleReplacing;
    }

    [DllImport("kernel32", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr LoadLibrary(string path);
    [DllImport("kernel32", CharSet=CharSet.Ansi, SetLastError=true)] static extern IntPtr GetProcAddress(IntPtr module, string name);
    [DllImport("kernel32")] static extern bool FreeLibrary(IntPtr module);

    sealed class Plugin : IDisposable {
        IntPtr module; public IntPtr Effect; public AEffect Info; public Dispatcher Dispatch;
        public SetParameter Set; public GetParameter Get; public ProcessReplacing Process;
        AudioMaster master; public int Rate = 44100, Block = 1024;
        public Plugin(string path) {
            module = LoadLibrary(path); if (module == IntPtr.Zero) throw new Exception("Windows could not load this 32-bit DLL. Error " + Marshal.GetLastWin32Error());
            IntPtr proc = GetProcAddress(module, "VSTPluginMain"); if (proc == IntPtr.Zero) proc = GetProcAddress(module, "main");
            if (proc == IntPtr.Zero) throw new Exception("This DLL has no VST2 entry point.");
            master = delegate(IntPtr e, int op, int i, IntPtr v, IntPtr p, float o) {
                if (op == 1) return new IntPtr(2400); if (op == 16) return new IntPtr(Rate); if (op == 17) return new IntPtr(Block); return IntPtr.Zero;
            };
            Effect = Marshal.GetDelegateForFunctionPointer<Entry>(proc)(master);
            if (Effect == IntPtr.Zero) throw new Exception("The plug-in returned no VST2 effect.");
            Info = Marshal.PtrToStructure<AEffect>(Effect); if (Info.magic != Magic) throw new Exception("The DLL returned an invalid VST2 effect.");
            Dispatch = Marshal.GetDelegateForFunctionPointer<Dispatcher>(Info.dispatcher);
            Set = Marshal.GetDelegateForFunctionPointer<SetParameter>(Info.setParameter); Get = Marshal.GetDelegateForFunctionPointer<GetParameter>(Info.getParameter);
            if (Info.processReplacing != IntPtr.Zero) Process = Marshal.GetDelegateForFunctionPointer<ProcessReplacing>(Info.processReplacing);
            Dispatch(Effect, EffOpen, 0, IntPtr.Zero, IntPtr.Zero, 0);
        }
        public string Text(int opcode, int index=0) { IntPtr b=Marshal.AllocHGlobal(256); try { for(int i=0;i<256;i++) Marshal.WriteByte(b,i,0); Dispatch(Effect,opcode,index,IntPtr.Zero,b,0); return Marshal.PtrToStringAnsi(b) ?? ""; } finally { Marshal.FreeHGlobal(b); } }
        public void Configure(int rate) { Rate=rate; Dispatch(Effect,EffSetRate,0,IntPtr.Zero,IntPtr.Zero,rate); Dispatch(Effect,EffSetBlock,0,new IntPtr(Block),IntPtr.Zero,0); }
        public void Dispose() { if(Effect!=IntPtr.Zero){Dispatch(Effect,EffClose,0,IntPtr.Zero,IntPtr.Zero,0);Effect=IntPtr.Zero;} if(module!=IntPtr.Zero){FreeLibrary(module);module=IntPtr.Zero;} GC.KeepAlive(master); }
    }

    class WaveData { public int Rate, Channels; public float[][] Samples; }
    static WaveData ReadWave(string path) {
        using(var r=new BinaryReader(File.OpenRead(path))) {
            if(new string(r.ReadChars(4))!="RIFF"){throw new Exception("Source is not RIFF WAV.");} r.ReadInt32(); if(new string(r.ReadChars(4))!="WAVE") throw new Exception("Source is not WAV.");
            short format=0,channels=0,bits=0; int rate=0; byte[] data=null;
            while(r.BaseStream.Position+8<=r.BaseStream.Length){string id=new string(r.ReadChars(4));int size=r.ReadInt32();long next=r.BaseStream.Position+size+(size&1);if(id=="fmt "){format=r.ReadInt16();channels=r.ReadInt16();rate=r.ReadInt32();r.ReadInt32();r.ReadInt16();bits=r.ReadInt16();}else if(id=="data")data=r.ReadBytes(size);r.BaseStream.Position=Math.Min(next,r.BaseStream.Length);}
            if(data==null||channels<1)throw new Exception("WAV contains no audio.");int bytes=bits/8,frames=data.Length/(channels*bytes);var samples=new float[channels][];for(int c=0;c<channels;c++)samples[c]=new float[frames];
            for(int f=0;f<frames;f++)for(int c=0;c<channels;c++){int o=(f*channels+c)*bytes;float v;if(format==3&&bits==32)v=BitConverter.ToSingle(data,o);else if(format==1&&bits==8)v=(data[o]-128)/128f;else if(format==1&&bits==16)v=BitConverter.ToInt16(data,o)/32768f;else if(format==1&&bits==24){int n=data[o]|data[o+1]<<8|data[o+2]<<16;if((n&0x800000)!=0)n|=unchecked((int)0xff000000);v=n/8388608f;}else if(format==1&&bits==32)v=BitConverter.ToInt32(data,o)/2147483648f;else throw new Exception("Unsupported WAV format.");samples[c][f]=v;}
            return new WaveData{Rate=rate,Channels=channels,Samples=samples};
        }
    }
    static void WriteWave(string path,int rate,float[][] samples){int ch=samples.Length,frames=samples[0].Length,dataSize=frames*ch*2;using(var w=new BinaryWriter(File.Create(path))){w.Write(Encoding.ASCII.GetBytes("RIFF"));w.Write(36+dataSize);w.Write(Encoding.ASCII.GetBytes("WAVEfmt "));w.Write(16);w.Write((short)1);w.Write((short)ch);w.Write(rate);w.Write(rate*ch*2);w.Write((short)(ch*2));w.Write((short)16);w.Write(Encoding.ASCII.GetBytes("data"));w.Write(dataSize);for(int f=0;f<frames;f++)for(int c=0;c<ch;c++)w.Write((short)Math.Max(-32768,Math.Min(32767,(int)Math.Round(samples[c][f]*32767))));}}
    static string B64(string s){return Convert.ToBase64String(Encoding.UTF8.GetBytes(s??""));}
    static int Main(string[] args){try{if(args.Length<2)throw new Exception("Usage: probe plugin.dll, or render plugin.dll source.wav target.wav params.txt");using(var p=new Plugin(args[1])){if(args[0]=="probe"){Console.WriteLine("PLUGIN\t"+B64(p.Text(EffEffectName)));for(int i=0;i<p.Info.numParams;i++)Console.WriteLine("PARAM\t"+i+"\t"+p.Get(p.Effect,i).ToString("R",CultureInfo.InvariantCulture)+"\t"+B64(p.Text(EffGetName,i))+"\t"+B64(p.Text(EffGetLabel,i))+"\t"+B64(p.Text(EffGetDisplay,i)));return 0;}if(args[0]=="render"&&args.Length>=5){var audio=ReadWave(args[2]);p.Configure(audio.Rate);foreach(var line in File.ReadAllLines(args[4])){var x=line.Split('=');if(x.Length==2)p.Set(p.Effect,int.Parse(x[0]),float.Parse(x[1],CultureInfo.InvariantCulture));}if(p.Process==null||(p.Info.flags&Replacing)==0)throw new Exception("Plug-in does not support replacing-process audio.");if(p.Info.numInputs<1)throw new Exception("Plug-in is an instrument, not an audio effect.");int frames=audio.Samples[0].Length,outs=Math.Max(1,p.Info.numOutputs);var rendered=new float[outs][];for(int c=0;c<outs;c++)rendered[c]=new float[frames];p.Dispatch(p.Effect,EffMains,0,new IntPtr(1),IntPtr.Zero,0);try{for(int start=0;start<frames;start+=p.Block){int count=Math.Min(p.Block,frames-start);var inHandles=new GCHandle[p.Info.numInputs];var outHandles=new GCHandle[outs];IntPtr inArray=Marshal.AllocHGlobal(IntPtr.Size*p.Info.numInputs),outArray=Marshal.AllocHGlobal(IntPtr.Size*outs);try{for(int c=0;c<p.Info.numInputs;c++){var block=new float[count];Array.Copy(audio.Samples[Math.Min(c,audio.Channels-1)],start,block,0,count);inHandles[c]=GCHandle.Alloc(block,GCHandleType.Pinned);Marshal.WriteIntPtr(inArray,c*IntPtr.Size,inHandles[c].AddrOfPinnedObject());}for(int c=0;c<outs;c++){var block=new float[count];outHandles[c]=GCHandle.Alloc(block,GCHandleType.Pinned);Marshal.WriteIntPtr(outArray,c*IntPtr.Size,outHandles[c].AddrOfPinnedObject());}p.Process(p.Effect,inArray,outArray,count);for(int c=0;c<outs;c++)Array.Copy((float[])outHandles[c].Target,0,rendered[c],start,count);}finally{foreach(var h in inHandles)if(h.IsAllocated)h.Free();foreach(var h in outHandles)if(h.IsAllocated)h.Free();Marshal.FreeHGlobal(inArray);Marshal.FreeHGlobal(outArray);}}}finally{p.Dispatch(p.Effect,EffMains,0,IntPtr.Zero,IntPtr.Zero,0);}WriteWave(args[3],audio.Rate,rendered);return 0;}}throw new Exception("Unknown bridge command.");}catch(Exception e){Console.Error.WriteLine(e.Message);return 1;}}
}
