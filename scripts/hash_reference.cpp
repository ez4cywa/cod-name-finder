#include <iostream>
#include <iomanip>
#include <string>
#include <cstddef>
#include "hash_mini.hpp"
// Independent reference calls into the attributed upstream MIT header.
int main() {
    for(const char* s: {"a", "A", "hello", "Weapons\\Rifle_Fire_01", "scripts/mp/_load.gsc", "weap_rex_mike4_fire_plr_01.qnn.85.48000.all"}) {
        auto row=[&](const char* id,uint64_t h) {std::cout<<id<<'\t'<<s<<'\t'<<std::hex<<h<<std::dec<<'\n';};
        row("iw-resource63",hash::HashIWAsset(s));row("fnv1a63",hash::HashX63(s));
        row("fnv1a64",hash::HashX64(s));row("fnv1a32",hash::HashX32(s));
        row("bo3-bo4-early-script32",hash::HashT7(s));row("bo4-bocw-script32",hash::HashT89Scr(s));
        row("mwii-mwiii-script64",hash::HashJupScr(s));row("mwii-mwiii-script63",hash::HashJupScr(s)&hash::MASK63);
        row("iw-dvar64",hash::HashIWDVar(s));row("bo6-script64",hash::HashT10Scr(s));
        row("bo6-sp-script64",hash::HashT10ScrSP(s));row("bo6-omnvar64",hash::HashT10OmnVar(s));
        row("prime32",hash::HashPrime(s));row("djb2-xor32",hash::HashDJB2(s));row("kvp64",hash::HashKVP(s));
        uint32_t sab32=5381;uint64_t sab64=0xcbf29ce484222325;uint64_t raw=0xcbf29ce484222325;
        for(const unsigned char* p=(const unsigned char*)s;*p;++p) {
            unsigned char c=(*p>='A'&&*p<='Z')?(*p-'A'+'a'):*p;
            sab32=sab32*65599+c;sab64=(sab64^c)*0x100000001b3;raw=(raw^*p)*0x100000001b3;
        }
        row("sab-sdbm32",sab32);row("sab-fnv1a64",sab64);row("fnv1a64-raw",raw);
    }
}
