use std::{collections::HashMap,slice,thread};
mod registry_generated;
use registry_generated::*;

#[no_mangle]
pub extern "C" fn hash_registry_sha256()->*const u8 {REGISTRY_SHA256.as_ptr()}
#[no_mangle]
pub extern "C" fn hash_registry_sha256_len()->usize {REGISTRY_SHA256.len()}

struct Hasher<'a> {h:u64,prime:u64,mask:u64,algorithm:u32,secret:&'a [u8],count:u64}
impl<'a> Hasher<'a> {
    fn step(&mut self,b:u8) {
        self.h=match self.algorithm {
            ALG_BO4_SCRIPT=> {let v=(self.h as u32).wrapping_add(b as u32);let m=v^(v<<10);m.wrapping_add(m>>6) as u64},
            ALG_PRIME32=> (self.h as u32).wrapping_mul(self.prime as u32).wrapping_add(b as u32) as u64,
            ALG_DJB2XOR=> ((self.h as u32).wrapping_mul(self.prime as u32)^(b as u32)) as u64,
            ALG_KVP=> self.h.wrapping_add(self.prime.wrapping_add(self.count).wrapping_mul(b as u64)),
            _=> (self.h^(b as u64)).wrapping_mul(self.prime),
        };
        self.count+=1;
    }
    fn update(&mut self,b:u8) {
        self.step(b);
        if self.algorithm==ALG_SECURE && self.count==1 {for &x in self.secret {self.step(x);}}
    }
    fn finish(mut self)->u64 {
        if self.algorithm==ALG_SUFFIX {for &x in self.secret {self.step(x);}}
        self.h=match self.algorithm {
            ALG_BO4_SCRIPT=> {let v=(self.h as u32).wrapping_mul(9);0x8001u32.wrapping_mul(v^(v>>11)) as u64},
            ALG_T7_SCRIPT=> self.h.wrapping_mul(self.prime),
            ALG_KVP=> self.h^((self.h^(self.h>>10))>>10),
            _=> self.h,
        };
        self.h & self.mask
    }
}

// FFI buffers are caller-owned, bounds-checked by Python, and live throughout the synchronous call.
#[no_mangle]
pub unsafe extern "C" fn hash_batch(data:*const u8,offsets:*const u32,count:usize,
    seed:u64,prime:u64,mask:u64,algorithm:u32,secret:*const u8,secret_len:usize,
    output:*mut u64,threads:usize) {
    if count==0{return;}
    let offsets=slice::from_raw_parts(offsets,count+1);
    let data=slice::from_raw_parts(data,offsets[count] as usize);
    let secret=slice::from_raw_parts(secret,secret_len);
    let out=slice::from_raw_parts_mut(output,count);
    let chunk=count.div_ceil(threads.max(1).min(64).min(count));
    thread::scope(|scope| {
        for (part,dst) in out.chunks_mut(chunk).enumerate() {
            scope.spawn(move || {
                for (local,target) in dst.iter_mut().enumerate() {
                    let i=part*chunk+local;
                    let mut h=Hasher {h:seed,prime,mask,algorithm,secret,count:0};
                    for &b in &data[offsets[i] as usize..offsets[i+1] as usize] {h.update(b);}
                    *target=h.finish();
                }
            });
        }
    });
}

#[no_mangle]
pub unsafe extern "C" fn hash_combinations(data:*const u8,offsets:*const u32,values:usize,
    starts:*const u32,radices:*const u32,slots:usize,base:u64,count:usize,
    seed:u64,prime:u64,mask:u64,algorithm:u32,secret:*const u8,secret_len:usize,
    targets:*const u64,target_count:usize,output:*mut u8,threads:usize) {
    if count==0 || slots==0{return;}
    let offsets=slice::from_raw_parts(offsets,values+1);
    let data=slice::from_raw_parts(data,offsets[values] as usize);
    let starts=slice::from_raw_parts(starts,slots);
    let radices=slice::from_raw_parts(radices,slots);
    let secret=slice::from_raw_parts(secret,secret_len);
    let targets=slice::from_raw_parts(targets,target_count);
    let out=slice::from_raw_parts_mut(output,count);
    let chunk=count.div_ceil(threads.max(1).min(64).min(count));
    thread::scope(|scope| {
        for (part,dst) in out.chunks_mut(chunk).enumerate() {
            scope.spawn(move || {
                let mut digits=vec![0usize;slots];
                for (local,hit) in dst.iter_mut().enumerate() {
                    let mut idx=base+(part*chunk+local) as u64;
                    for s in (0..slots).rev() {digits[s]=(idx%radices[s] as u64) as usize;idx/=radices[s] as u64;}
                    let mut h=Hasher {h:seed,prime,mask,algorithm,secret,count:0};
                    for s in 0..slots {
                        let v=starts[s] as usize+digits[s];
                        for &b in &data[offsets[v] as usize..offsets[v+1] as usize] {h.update(b);}
                    }
                    *hit=u8::from(targets.binary_search(&h.finish()).is_ok());
                }
            });
        }
    });
}

// Independently implemented meet-in-the-middle search.  A contiguous low-bit
// mask is a closed ring for multiply/xor/add: 63-bit ids do NOT reveal the lost
// top bit of the full state.  Working modulo 2^63 represents both full64 lifts
// exactly, without making a guess about that flag bit.
struct Peel {
    data:Vec<u8>,offsets:Vec<u32>,starts:Vec<u32>,radices:Vec<u32>,split:usize,
    seed:u64,prime:u64,mask:u64,algorithm:u32,secret:Vec<u8>,targets:Vec<u64>,
    tails:u64,heads:u64,direction:u32,empty_heads:bool,
    table:HashMap<(u64,bool),Vec<u64>>,
}
impl Peel {
    fn bytes(&self,index:u64,begin:usize,end:usize)->Vec<u8> {
        let mut idx=index;
        let mut digits=vec![0usize;end-begin];
        for slot in (begin..end).rev() {
            digits[slot-begin]=(idx%self.radices[slot] as u64) as usize;
            idx/=self.radices[slot] as u64;
        }
        let mut result=Vec::new();
        for slot in begin..end {
            let value=self.starts[slot] as usize+digits[slot-begin];
            result.extend_from_slice(&self.data[self.offsets[value] as usize..self.offsets[value+1] as usize]);
        }
        result
    }
    fn head(&self,index:u64)->(u64,bool) {
        let mut h=Hasher {h:self.seed,prime:self.prime,mask:self.mask,
            algorithm:self.algorithm,secret:&self.secret,count:0};
        // Consume slot slices directly: no full candidate allocation or Python
        // product enumeration sits on the native hot path.
        let mut idx=index;
        let mut digits=vec![0usize;self.split];
        for slot in (0..self.split).rev() {
            digits[slot]=(idx%self.radices[slot] as u64) as usize;
            idx/=self.radices[slot] as u64;
        }
        for (slot,digit) in digits.iter().enumerate() {
            let value=self.starts[slot] as usize+digit;
            for &byte in &self.data[self.offsets[value] as usize..self.offsets[value+1] as usize] {h.update(byte);}
        }
        (h.h&self.mask,self.algorithm==ALG_SECURE && h.count==0)
    }
    fn reverse(&self,mut h:u64,tail:&[u8],empty:bool,inv:u64,steps:&mut u64)->u64 {
        let step=|state:u64,byte:u8|->u64 {
            match self.algorithm {
                ALG_PRIME32=> state.wrapping_sub(byte as u64).wrapping_mul(inv)&self.mask,
                ALG_DJB2XOR=> (state^(byte as u64)).wrapping_mul(inv)&self.mask,
                _=> (state.wrapping_mul(inv)^(byte as u64))&self.mask,
            }
        };
        if self.algorithm==ALG_T7_SCRIPT {h=h.wrapping_mul(inv)&self.mask;*steps+=1;}
        if self.algorithm==ALG_SUFFIX {
            for &byte in self.secret.iter().rev() {h=step(h,byte);*steps+=1;}
        }
        if self.algorithm==ALG_SECURE && empty && !tail.is_empty() {
            for &byte in tail[1..].iter().rev() {h=step(h,byte);*steps+=1;}
            for &byte in self.secret.iter().rev() {h=step(h,byte);*steps+=1;}
            h=step(h,tail[0]);*steps+=1;
        } else {
            for &byte in tail.iter().rev() {h=step(h,byte);*steps+=1;}
        }
        h
    }
}
fn odd_inverse(prime:u64)->u64 {
    // Newton iteration doubles the number of correct low bits each step.
    let mut inverse=prime;
    for _ in 0..6 {inverse=inverse.wrapping_mul(2u64.wrapping_sub(prime.wrapping_mul(inverse)));}
    inverse
}

// stats = [forward head hashes, reverse byte operations, table entries].
// The returned opaque owner has a matching destroy function; no caller buffer
// is retained. Invalid geometry/noninvertible/finalizer profiles return null.
#[no_mangle]
pub unsafe extern "C" fn hash_peel_new(data:*const u8,offsets:*const u32,values:usize,
    starts:*const u32,radices:*const u32,slots:usize,split:usize,direction:u32,
    seed:u64,prime:u64,mask:u64,algorithm:u32,secret:*const u8,secret_len:usize,
    targets:*const u64,target_count:usize,stats:*mut u64)->*mut std::ffi::c_void {
    if slots<2 || split==0 || split>=slots || direction>1 || prime&1==0 ||
        !matches!(algorithm,ALG_FNV|ALG_T7_SCRIPT|ALG_SECURE|ALG_SUFFIX|ALG_PRIME32|ALG_DJB2XOR) ||
        !matches!(mask,0xffff_ffff|0x7fff_ffff_ffff_ffff|0xffff_ffff_ffff_ffff) ||
        (matches!(algorithm,ALG_PRIME32|ALG_DJB2XOR) && mask!=0xffff_ffff) {return std::ptr::null_mut();}
    let offsets=slice::from_raw_parts(offsets,values+1).to_vec();
    let data=slice::from_raw_parts(data,offsets[values] as usize).to_vec();
    let starts=slice::from_raw_parts(starts,slots).to_vec();
    let radices=slice::from_raw_parts(radices,slots).to_vec();
    if radices.contains(&0) {return std::ptr::null_mut();}
    let product=|a:&[u32]| a.iter().try_fold(1u64,|v,&x|v.checked_mul(x as u64));
    let (Some(heads),Some(tails))=(product(&radices[..split]),product(&radices[split..])) else {return std::ptr::null_mut();};
    let empty_heads=algorithm==ALG_SECURE && (0..split).all(|slot| {
        (0..radices[slot] as usize).any(|digit| {
            let value=starts[slot] as usize+digit;
            offsets[value]==offsets[value+1]
        })
    });
    let entries=if direction==0 {tails.checked_mul(target_count as u64).and_then(|n|n.checked_mul(if empty_heads {2}else{1}))} else {Some(heads)};
    if entries.is_none_or(|n|n>2_000_000) {return std::ptr::null_mut();}
    let mut state=Box::new(Peel {data,offsets,starts,radices,split,seed,prime,mask,algorithm,
        secret:slice::from_raw_parts(secret,secret_len).to_vec(),
        targets:slice::from_raw_parts(targets,target_count).iter().copied().filter(|h|h&mask==*h).collect(),
        tails,heads,direction,empty_heads,table:HashMap::new()});
    let mut counts=[0u64;3];
    let inverse=odd_inverse(prime);
    if direction==0 {
        for tail_index in 0..tails {
            let tail=state.bytes(tail_index,split,slots);
            for &target in &state.targets {
                for empty in [false,true].into_iter().take(if empty_heads {2}else{1}) {
                    let key=(state.reverse(target,&tail,empty,inverse,&mut counts[1]),empty);
                    state.table.entry(key).or_default().push(tail_index);counts[2]+=1;
                }
            }
        }
        for values in state.table.values_mut() {values.sort_unstable();values.dedup();}
    } else {
        for head_index in 0..heads {
            let key=state.head(head_index);
            state.table.entry(key).or_default().push(head_index);counts[0]+=1;counts[2]+=1;
        }
    }
    slice::from_raw_parts_mut(stats,3).copy_from_slice(&counts);
    Box::into_raw(state).cast()
}

#[no_mangle]
pub unsafe extern "C" fn hash_peel_free(owner:*mut std::ffi::c_void) {
    if !owner.is_null() {drop(Box::from_raw(owner.cast::<Peel>()));}
}

// Work is limited to the exact original mixed-radix interval. Returned flags
// still use base+local, so partial budgets, checkpoint cursors, and pause are
// identical to a forward scan even when its edges split a head/tail product.
#[no_mangle]
pub unsafe extern "C" fn hash_peel_scan(owner:*const std::ffi::c_void,base:u64,count:usize,
    output:*mut u8,stats:*mut u64) {
    if owner.is_null() || count==0 {return;}
    let state=&*owner.cast::<Peel>();
    let Some(end)=base.checked_add(count as u64) else {return;};
    if end>state.heads.saturating_mul(state.tails) {return;}
    let out=slice::from_raw_parts_mut(output,count);out.fill(0);
    let mut counts=[0u64;3];
    if state.direction==0 {
        for head_index in base/state.tails..=(end-1)/state.tails {
            let key=state.head(head_index);counts[0]+=1;
            if let Some(tails)=state.table.get(&key) {
                let head_base=head_index*state.tails;
                for &tail in tails {
                    let index=head_base+tail;
                    if index>=base && index<end {out[(index-base) as usize]=1;}
                }
            }
        }
    } else {
        let inverse=odd_inverse(state.prime);
        let first=base%state.tails;
        let span=end-base;
        // At most two clipped tail ranges are necessary at an interval edge.
        let ranges=if span>=state.tails {vec![(0,state.tails)]}
            else if first+span<=state.tails {vec![(first,first+span)]}
            else {vec![(first,state.tails),(0,first+span-state.tails)]};
        for (begin,last) in ranges {
            for tail_index in begin..last {
                let tail=state.bytes(tail_index,state.split,state.radices.len());
                for &target in &state.targets {
                    for empty in [false,true].into_iter().take(if state.empty_heads {2}else{1}) {
                        let key=(state.reverse(target,&tail,empty,inverse,&mut counts[1]),empty);
                        if let Some(heads)=state.table.get(&key) {
                            for &head in heads {
                                let index=head*state.tails+tail_index;
                                if index>=base && index<end {out[(index-base) as usize]=1;}
                            }
                        }
                    }
                }
            }
        }
    }
    slice::from_raw_parts_mut(stats,3).copy_from_slice(&counts);
}
